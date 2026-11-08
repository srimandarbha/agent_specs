# Design: Drain Annotation or Uncordon Coordination Mismatch

## Design Objective
Diagnose **drain completion annotation or uncordon coordination mismatch**, determine whether the desynchronization is caused by competing external uncordon or dropped annotation updates post-drain, and generate a deterministic remediation specification (Ansible Playbook spec or manual CLI fallback) without relying on direct cluster mutation.

---

## Evidence-First Flow

1. **Establish Identity & Context**
   - Cluster ID, MachineConfigPool, target node, and time window.
   - Pinned OpenShift release and release-matched runbook.
2. **Confirm Lifecycle Stage**
   - Trigger signal: MCC/MCD logs report uncordon during update or mismatch between desired/applied drain annotations.
   - Confirm active stage is `drain` or `waiting-for-drain`.
3. **Execute Single Multi-Index Search**
   - Query `query_unified_splunk_dossier` spanning `index=ocp_logs`, `index=k8s_objects` / KV Store, and `index=ocp_metrics`.
4. **Causal Correlation & Classification**
   - Retrieve Node coordination state: `spec.unschedulable`, `desiredDrain`, `lastAppliedDrain`.
   - Traverse causal sub-tree:
     - Branch 3A: `spec.unschedulable == false` mid-update? Competing automation uncordoned node.
     - Branch 3B: `desiredDrain != lastAppliedDrain` and 0 drainable pods remain? MCC 409 Conflict dropped annotation write.
     - Branch 3C: `lastAppliedDrain == desiredDrain` but user pods actively running? Forged completion annotation.
5. **Remediation Matching**
   - Evaluate against `remediations/PLAYBOOK_CATALOG.json`.
   - If Branch 3A or 3B $\rightarrow$ generate `playbook_reconcile_drain_annotation` spec with validated `extra_vars`.
   - If Branch 3C or unknown competing controller $\rightarrow$ generate targeted manual `oc` CLI fallback with safety checks.
6. **Persist & Verify**
   - Record investigation state and evidence IDs in PostgreSQL (`db/migrations/001_initial.sql`).
   - Monitor for recovery post-execution: Node cordoned, annotations match, MCD logs show machine config application starting.

---

## State Model
`TRIGGERED -> CONTEXT_CAPTURED -> UNIFIED_DOSSIER_COLLECTED -> ROOT_CAUSE_DIAGNOSED -> REMEDIATION_MATCHED (AAP Playbook OR Manual CLI) -> PERSISTED`

---

## Data Contract
* **Investigation Record:** `investigation_id`, `cluster_id`, `node_name`, `desired_drain`, `last_applied_drain`, `is_schedulable`.
* **Evidence Citations:** `mcc_coordination_error_log`, `node_annotation_snapshot`, `node_pod_count`.
* **Remediation Specification:**
  * If automated: `{ playbook_id: "playbook_reconcile_drain_annotation", aap_extra_vars: { ... } }`.
  * If manual: `{ manual_cli_commands: [ ... ], safety_warnings: "...", rollback_steps: "..." }`.

---

## Guardrails
- Strictly read-only execution in the diagnostic agent.
- No direct `oc patch node` executed autonomously.
- Never forge completion annotations while pods remain on the node.
- Secret and credential values are stripped before persistence.
