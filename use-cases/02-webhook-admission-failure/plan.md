# Implementation Plan: Admission Webhook Blocks Pod Deletion or Eviction

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Phase 0: Ground Truth & Telemetry Alignment
- [ ] Pin supported OpenShift release(s) and obtain matching MCO source/runbook revision.
- [ ] Align trigger signals in Splunk: MCC or API server logs report `failed calling webhook` during eviction.
- [ ] Confirm `index=ocp_logs`, `index=k8s_objects` (with `managedFields` stripped), and `index=ocp_metrics` (`apiserver_admission_webhook_rejection_count`) are populated.
- [ ] Verify that `Pod` and `Node` objects are cached in the Splunk KV Store (`k8s_live_inventory_lookup`) for instant retrieval.

## Phase 1: Read-Only Evidence Tooling
- [ ] Implement the parameterized **Unified Multi-Index Splunk Search** (`query_unified_splunk_dossier`).
- [ ] Bound search time: `earliest=-1h latest=now` for logs/metrics; `earliest=-24h` for objects (or instant KV Store lookup).
- [ ] Normalize timestamps, cluster ID, webhook name, and target pod names into structured state.
- [ ] Redact secrets, authorization headers, and environment variables.

## Phase 2: Causal Reasoning & Classification
- [ ] Extract failing pod and webhook name from MCC/apiserver logs.
- [ ] If webhook is `virt-launcher-eviction-interceptor`, immediately hand off to `05-ocv-vm-not-migratable`.
- [ ] **Multi-level Root Cause Analysis:**
  - Has the webhook controller deployment crashed or scaled to 0 replicas?
  - Has the webhook server TLS certificate expired (`x509` error)?
  - Is an ingress NetworkPolicy or firewall blocking API server communication to the webhook pod?

## Phase 3: Two-Tier Remediation & Playbook Matching
- [ ] **Catalog Matching:** Evaluate against [`remediations/PLAYBOOK_CATALOG.json`](../../remediations/PLAYBOOK_CATALOG.json):
  - Autonomous mutation of admission webhooks is **strictly prohibited** (`matched: false`).
- [ ] **Intelligent CLI Fallback:**
  - For crashed controllers: output deployment restart and log inspection runbook.
  - For expired certificates: output service-ca secret rotation steps.
  - For emergency bypass: output security-gated `failurePolicy: Ignore` patch instructions with explicit rollback verification.
- [ ] Keep all mutation tools disabled inside the agent; hand off execution to human SRE and security administrators.

## Phase 4: Verification & Acceptance Tests
- [ ] Unit tests: matching trigger, non-matching trigger, incomplete evidence, and contradictory evidence.
- [ ] Graph test: single multi-index query completes within 10s; graph completes within 45s deadline.
- [ ] Interceptor test: KubeVirt interceptor correctly redirects to 05 without classifying as webhook outage.
- [ ] Safety test: verify agent strictly refuses autonomous deletion of webhook configurations.
- [ ] Post-remediation verification: Webhook endpoints healthy, eviction succeeds, and MCC drain resumes.

---

## Observability & Graph Integration Contract

### Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Controller drain logs, kube-apiserver admission logs, webhook pod logs.
* `index=k8s_objects` / KV Store: `Pod` (blocker pod), `Node` (cordon status).
* `index=ocp_metrics`: `apiserver_admission_webhook_rejection_count`, `apiserver_admission_webhook_admission_duration_seconds`.

### Bounded Execution
* Max 2 Splunk tool calls total per investigation.
* 15-second per-query timeout; 45-second overall investigation deadline.
* Stop as `inconclusive` if cluster identity is ambiguous or required telemetry is unavailable.
