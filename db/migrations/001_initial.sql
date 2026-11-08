-- PostgreSQL case memory schema. Apply through a migration runner in a transaction.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS sre_investigations (
  investigation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key TEXT NOT NULL UNIQUE,
  trigger_type TEXT NOT NULL CHECK (trigger_type IN ('alert','manual')),
  cluster_id TEXT NOT NULL,
  cluster_name TEXT NOT NULL,
  openshift_version TEXT,
  node_name TEXT,
  mcp_name TEXT,
  lifecycle_stage TEXT NOT NULL DEFAULT 'unknown',
  use_case_id TEXT,
  skill_version TEXT,
  status TEXT NOT NULL CHECK (status IN ('running','diagnosed','inconclusive','unclassified_anomaly','failed')) DEFAULT 'running',
  diagnosis_status TEXT CHECK (diagnosis_status IN ('supported','probable','inconclusive','no_matching_skill','version_gate_failed','unclassified_anomaly')),
  root_cause_hypothesis TEXT,
  confidence_band TEXT CHECK (confidence_band IN ('low','medium','high','exploratory')),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  deadline_at TIMESTAMPTZ,
  summary TEXT,
  missing_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
  safety_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sre_evidence (
  evidence_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  investigation_id UUID NOT NULL REFERENCES sre_investigations(investigation_id) ON DELETE CASCADE,
  source TEXT NOT NULL CHECK (source IN ('splunk','prometheus','kubernetes_api')),
  tool_name TEXT NOT NULL,
  request_id TEXT,
  query_or_request_redacted TEXT,
  cluster_id TEXT NOT NULL,
  resource_ref TEXT,
  event_time TIMESTAMPTZ,
  observed_at TIMESTAMPTZ NOT NULL,
  ingested_at TIMESTAMPTZ,
  result_summary TEXT NOT NULL,
  source_uri TEXT,
  content_hash TEXT,
  freshness TEXT NOT NULL CHECK (freshness IN ('fresh','stale','unknown')) DEFAULT 'unknown',
  redaction_status TEXT NOT NULL DEFAULT 'redacted',
  attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sre_hypotheses (
  hypothesis_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  investigation_id UUID NOT NULL REFERENCES sre_investigations(investigation_id) ON DELETE CASCADE,
  hypothesis TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('supported','contradicted','unresolved')),
  rationale TEXT NOT NULL,
  supporting_evidence_ids UUID[] NOT NULL DEFAULT '{}',
  contradicting_evidence_ids UUID[] NOT NULL DEFAULT '{}',
  confidence_band TEXT CHECK (confidence_band IN ('low','medium','high','exploratory')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sre_recommendations (
  recommendation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  investigation_id UUID NOT NULL REFERENCES sre_investigations(investigation_id) ON DELETE CASCADE,
  recommendation TEXT NOT NULL,
  risk_level TEXT NOT NULL CHECK (risk_level IN ('low','medium','high','disruptive','unknown')),
  requires_human_approval BOOLEAN NOT NULL DEFAULT true,
  execution_allowed BOOLEAN NOT NULL DEFAULT false CHECK (execution_allowed = false),
  verification_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sre_knowledge (
  knowledge_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  use_case_id TEXT NOT NULL,
  knowledge_type TEXT NOT NULL CHECK (knowledge_type IN ('verified_pattern','runbook_reference','release_note','anti_pattern')),
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  source_uri TEXT,
  source_revision TEXT,
  openshift_version_range TEXT,
  verification_status TEXT NOT NULL CHECK (verification_status IN ('unverified','verified','deprecated')) DEFAULT 'unverified',
  verified_by TEXT,
  last_verified_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sre_inv_cluster_time_idx ON sre_investigations(cluster_id, started_at DESC);
CREATE INDEX IF NOT EXISTS sre_inv_case_status_idx ON sre_investigations(use_case_id, status, started_at DESC);
CREATE INDEX IF NOT EXISTS sre_evidence_inv_time_idx ON sre_evidence(investigation_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS sre_evidence_resource_time_idx ON sre_evidence(cluster_id, resource_ref, observed_at DESC);
CREATE INDEX IF NOT EXISTS sre_hypotheses_inv_idx ON sre_hypotheses(investigation_id, status);
CREATE INDEX IF NOT EXISTS sre_knowledge_case_verified_idx ON sre_knowledge(use_case_id, verification_status, last_verified_at DESC);

-- Operational notes:
-- 1. Grant the agent INSERT/SELECT on incident tables and SELECT on verified knowledge only.
-- 2. Keep schema migrations owned by deployment/admin role, not the runtime agent.
-- 3. Add pgvector in a later migration only after retrieval evaluation and retention/security review.
-- 4. Configure backup, retention, encryption at rest/in transit, and row-level security per tenancy.
