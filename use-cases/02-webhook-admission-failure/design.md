# Design: Admission Webhook Blocks Pod Deletion or Eviction

## Design Objective
Diagnose **admission webhook blocks pod deletion or eviction**, distinguish third-party webhook infrastructure failures from the KubeVirt live migration interceptor, isolate whether the root cause is a crashed backend pod, an expired TLS certificate, or a network policy block, and generate a deterministic manual CLI fallback specification without direct cluster mutation.

---

## Evidence-First Flow

1. **Establish Identity & Context**
   - Cluster ID, MachineConfigPool, target node, and time window.
   - Pinned OpenShift release and release-matched runbook.
2. **Confirm Lifecycle Stage**
   - Trigger signal: Eviction request rejected by admission webhook.
   - Confirm active stage is `drain`.
3. **Execute Single Multi-Index Search**
   - Query `query_unified_splunk_dossier` spanning `index=ocp_logs`, `index=k8s_objects` / KV Store, and `index=ocp_metrics`.
4. **Causal Correlation & Classification**
   - Check webhook name: If `virt-launcher-eviction-interceptor`, handoff to `05-ocv-vm-not-migratable`.
   - Inspect webhook error reason from apiserver logs.
   - Traverse causal sub-tree:
     - Branch 3A: `connection refused` or 0 endpoints? Webhook controller crash.
     - Branch 3B: `x509: certificate has expired`? TLS certificate expiration.
     - Branch 3C: `context deadline exceeded` with pod running? NetworkPolicy or firewall block.
5. **Remediation Matching**
   - Automated remediation strictly prohibited (`matched: false`).
   - Generate targeted manual `oc` CLI fallback with controller restart or certificate rotation steps.
6. **Persist & Verify**
   - Record investigation state and evidence IDs in PostgreSQL (`db/migrations/001_initial.sql`).
   - Monitor for recovery post-execution: Webhook endpoints healthy, eviction succeeds, MCC drain resumes.

---

## State Model
`TRIGGERED -> CONTEXT_CAPTURED -> UNIFIED_DOSSIER_COLLECTED -> ROOT_CAUSE_DIAGNOSED -> REMEDIATION_MATCHED (Manual CLI Fallback) -> PERSISTED`

---

## Data Contract
* **Investigation Record:** `investigation_id`, `cluster_id`, `node_name`, `target_namespace`, `webhook_name`, `error_type`.
* **Evidence Citations:** `apiserver_admission_error_log`, `webhook_endpoint_snapshot`, `mcc_drain_log`.
* **Remediation Specification:**
  * `{ manual_cli_commands: [ ... ], safety_warnings: "...", rollback_steps: "..." }`.

---

## Guardrails
- Strictly read-only execution in the diagnostic agent.
- NEVER delete webhook configurations autonomously.
- Secret and credential values are stripped before persistence.
