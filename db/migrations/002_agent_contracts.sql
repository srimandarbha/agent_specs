-- Additive migration: structured recommendations, approvals and audit events.
-- Apply with the migration role in a transaction; runtime agent must not have DDL.

ALTER TABLE sre_recommendations
  ADD COLUMN IF NOT EXISTS recommendation_reference TEXT,
  ADD COLUMN IF NOT EXISTS playbook_id TEXT,
  ADD COLUMN IF NOT EXISTS catalog_revision TEXT,
  ADD COLUMN IF NOT EXISTS artifact_revision TEXT,
  ADD COLUMN IF NOT EXISTS recommendation_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'not_requested',
  ADD COLUMN IF NOT EXISTS approval_reference TEXT,
  ADD COLUMN IF NOT EXISTS approval_payload_hash TEXT,
  ADD COLUMN IF NOT EXISTS external_execution_status TEXT NOT NULL DEFAULT 'not_started',
  ADD COLUMN IF NOT EXISTS external_execution_reference TEXT,
  ADD COLUMN IF NOT EXISTS external_execution_started_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS external_execution_completed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS verification_status TEXT NOT NULL DEFAULT 'not_started',
  ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;

ALTER TABLE sre_recommendations
  ADD CONSTRAINT sre_recommendations_approval_status_check
    CHECK (approval_status IN ('not_requested','pending','approved','rejected','expired','revoked')),
  ADD CONSTRAINT sre_recommendations_external_execution_status_check
    CHECK (external_execution_status IN ('not_started','submitted','queued','running','succeeded','failed','cancelled','unknown')),
  ADD CONSTRAINT sre_recommendations_verification_status_check
    CHECK (verification_status IN ('not_started','pending','recovered','not_recovered','inconclusive'));

-- Note: recommendation_id (UUID PK) is created in 001_initial.sql. recommendation_reference stores optional human-readable business tracking keys.
CREATE UNIQUE INDEX IF NOT EXISTS sre_recommendations_rec_ref_idx
  ON sre_recommendations(recommendation_reference)
  WHERE recommendation_reference IS NOT NULL;

CREATE INDEX IF NOT EXISTS sre_recommendations_execution_ref_idx
  ON sre_recommendations(external_execution_reference)
  WHERE external_execution_reference IS NOT NULL;

-- Append-only transition and audit journal. Do not store raw secrets or complete log payloads here.
CREATE TABLE IF NOT EXISTS sre_investigation_events (
  event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  investigation_id UUID NOT NULL REFERENCES sre_investigations(investigation_id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  event_time TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor_type TEXT NOT NULL CHECK (actor_type IN ('agent','human','adapter','collector','aap_service','system')),
  actor_id TEXT,
  correlation_id TEXT,
  idempotency_key TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  payload_hash TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sre_inv_events_inv_time_idx
  ON sre_investigation_events(investigation_id, event_time);

CREATE UNIQUE INDEX IF NOT EXISTS sre_inv_events_idempotency_idx
  ON sre_investigation_events(investigation_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

-- Persist deterministic joins and their provenance, rather than asking an LLM to reconstruct them.
CREATE TABLE IF NOT EXISTS sre_evidence_relationships (
  relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  investigation_id UUID NOT NULL REFERENCES sre_investigations(investigation_id) ON DELETE CASCADE,
  from_evidence_id UUID NOT NULL REFERENCES sre_evidence(evidence_id) ON DELETE CASCADE,
  to_evidence_id UUID NOT NULL REFERENCES sre_evidence(evidence_id) ON DELETE CASCADE,
  relationship_type TEXT NOT NULL,
  join_rule TEXT NOT NULL,
  result TEXT NOT NULL CHECK (result IN ('confirmed','candidate','ambiguous','rejected','unavailable')) ,
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (from_evidence_id <> to_evidence_id)
);

CREATE INDEX IF NOT EXISTS sre_evidence_relationships_inv_idx
  ON sre_evidence_relationships(investigation_id, created_at);

CREATE INDEX IF NOT EXISTS sre_inv_events_type_time_idx
  ON sre_investigation_events(event_type, event_time DESC);

-- Adapter/source vocabulary is deliberately constrained to the deployed evidence path.
-- Existing historical `kubernetes_api` rows are retained for audit; new runtime code must
-- reject that adapter in the read-only no-Kubernetes-API deployment profile.
ALTER TABLE sre_evidence
  ADD COLUMN IF NOT EXISTS adapter_version TEXT,
  ADD COLUMN IF NOT EXISTS schema_version TEXT,
  ADD COLUMN IF NOT EXISTS query_template_id TEXT,
  ADD COLUMN IF NOT EXISTS source_revision TEXT,
  ADD COLUMN IF NOT EXISTS event_type TEXT,
  ADD COLUMN IF NOT EXISTS metric_name TEXT,
  ADD COLUMN IF NOT EXISTS metric_labels JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS metric_value DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS metric_unit TEXT,
  ADD COLUMN IF NOT EXISTS resource_uid TEXT,
  ADD COLUMN IF NOT EXISTS resource_version TEXT,
  ADD COLUMN IF NOT EXISTS evidence_quality TEXT NOT NULL DEFAULT 'valid'
    CHECK (evidence_quality IN ('valid','partial','malformed','contradictory'));

CREATE INDEX IF NOT EXISTS sre_evidence_metric_idx
  ON sre_evidence(cluster_id, metric_name, event_time DESC)
  WHERE metric_name IS NOT NULL;

CREATE INDEX IF NOT EXISTS sre_evidence_resource_uid_idx
  ON sre_evidence(cluster_id, resource_uid, observed_at DESC)
  WHERE resource_uid IS NOT NULL;

-- Explicit retention metadata. Actual deletion/archival is owned by a scheduled maintenance job.
ALTER TABLE sre_investigations
  ADD COLUMN IF NOT EXISTS retention_class TEXT NOT NULL DEFAULT 'standard',
  ADD COLUMN IF NOT EXISTS source_event_id TEXT,
  ADD COLUMN IF NOT EXISTS registry_revision TEXT,
  ADD COLUMN IF NOT EXISTS model_id TEXT,
  ADD COLUMN IF NOT EXISTS prompt_version TEXT,
  ADD COLUMN IF NOT EXISTS skill_content_hash TEXT;

CREATE INDEX IF NOT EXISTS sre_inv_source_event_idx
  ON sre_investigations(cluster_id, source_event_id)
  WHERE source_event_id IS NOT NULL;

-- Runtime permission guidance:
-- * Migration role: DDL and index management.
-- * Agent role: SELECT/INSERT/UPDATE only on explicitly required tables/columns.
-- * Agent role must not update approval or external execution fields; only the approval/AAP
--   integration identity may do so. Enforce with separate database roles/column privileges.
-- * Track B recommendation writes must persist playbook_match=false and playbook_id=NULL.
