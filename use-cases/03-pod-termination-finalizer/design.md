# Design: Pod Remains Terminating or Finalizer Cleanup Stalls

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Design Objective
Diagnose **pod remains terminating or finalizer cleanup stalls**, isolate whether the stall is due to an un-reconciled operator finalizer, a storage unmount interlock, or a hung container runtime process, and generate a deterministic remediation specification (manual CLI fallback or storage playbook handoff) without relying on direct cluster mutation.

---

## Evidence-First Flow

1. **Establish Identity & Context**
   - Cluster ID, MachineConfigPool, target node, and time window.
   - Pinned OpenShift release and release-matched runbook.
2. **Confirm Lifecycle Stage**
   - Trigger signal: MCC log contains `error when waiting for pod ... to terminate`.
   - Confirm active stage is `drain` (node cordoned, pods evicting).
3. **Execute Single Multi-Index Search**
   - Query `query_unified_splunk_dossier` spanning `index=ocp_logs`, `index=k8s_objects` / KV Store, and `index=ocp_metrics`.
4. **Causal Correlation & Classification**
   - Map MCC termination error pod to `k8s_objects` / KV Store.
   - Verify `metadata.deletionTimestamp` is set and evaluate `metadata.finalizers`.
   - Traverse causal sub-tree:
     - Branch 3A: Non-empty operator/custom finalizer? Correlate controlling operator health in `ocp_logs`.
     - Branch 3B: Storage finalizer (`kubernetes.io/pvc-protection`)? Correlate VolumeAttachment status.
     - Branch 3C: Empty finalizers and grace period exceeded? Correlate `FailedKillPod` events and Kubelet/CRI-O logs.
5. **Remediation Matching**
   - Autonomous finalizer stripping is prohibited.
   - If Branch 3B is met and CSI RPC hang is isolated $\rightarrow$ handoff to `playbook_restart_csi_driver`.
   - Otherwise $\rightarrow$ generate targeted manual `oc` CLI fallback with safety checks (operator recovery or CRI-O debugging).
6. **Persist & Verify**
   - Record investigation state and evidence IDs in PostgreSQL (`db/migrations/001_initial.sql`).
   - Monitor for recovery post-execution: Pod record disappears from KV Store, no new `FailedKillPod` events, MCC drain resumes.

---

## State Model
`TRIGGERED -> CONTEXT_CAPTURED -> UNIFIED_DOSSIER_COLLECTED -> ROOT_CAUSE_DIAGNOSED -> REMEDIATION_MATCHED (Manual CLI Fallback or Storage Playbook) -> PERSISTED`

---

## Data Contract
* **Investigation Record:** `investigation_id`, `cluster_id`, `node_name`, `target_namespace`, `failing_pod`, `finalizers_list`.
* **Evidence Citations:** `mcc_termination_error_log`, `pod_metadata_snapshot`, `failed_kill_pod_events`, `operator_log_excerpt`.
* **Remediation Specification:**
  * If storage handoff: `{ playbook_id: "playbook_restart_csi_driver", aap_extra_vars: { ... } }`.
  * If manual runbook: `{ manual_cli_commands: [ ... ], safety_warnings: "...", rollback_steps: "..." }`.

---

## Guardrails
- Strictly read-only execution in the diagnostic agent.
- No direct `oc patch` or `oc delete pod --force` executed autonomously.
- Never strip finalizers without confirming external resource status.
- Secret and credential values are stripped before persistence.
