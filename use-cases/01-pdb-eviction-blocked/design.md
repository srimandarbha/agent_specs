# Design: PodDisruptionBudget Blocks Eviction

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Design Objective
Diagnose **PodDisruptionBudget blocks eviction**, isolate the root cause behind the zero-disruption allowance, and generate a deterministic remediation specification (Ansible Playbook spec or manual CLI fallback) without relying on direct cluster mutation.

---

## Evidence-First Flow

1. **Establish Identity & Context**
   - Cluster ID, MachineConfigPool, target node, and time window.
   - Pinned OpenShift release and release-matched runbook.
2. **Confirm Lifecycle Stage**
   - Trigger signal: MCC log contains `Cannot evict pod as it would violate the pod's disruption budget`.
   - Confirm active stage is `drain` (not post-drain apply/reboot/uncordon).
3. **Execute Single Multi-Index Search**
   - Query `query_unified_splunk_dossier` spanning `index=ocp_logs`, `index=k8s_objects` / KV Store, and `index=ocp_metrics`.
4. **Causal Correlation & Classification**
   - Map MCC eviction error pod to PDB via label selector in the target namespace.
   - Confirm `disruptionsAllowed: 0`.
   - Traverse causal sub-tree:
     - Sibling replica in CrashLoopBackOff / unready?
     - Single-replica workload with minAvailable=1?
     - Node capacity / anti-affinity deadlock?
5. **Remediation Matching**
   - Evaluate against `remediations/PLAYBOOK_CATALOG.json`.
   - If match $\rightarrow$ generate `playbook_pdb_scale_up` spec with validated `extra_vars`.
   - If no match $\rightarrow$ generate targeted manual `oc` CLI fallback with safety checks.
6. **Persist & Verify**
   - Record investigation state and evidence IDs in PostgreSQL (`db/migrations/001_initial.sql`).
   - Monitor for recovery post-execution: MCC logs show blocker evicted, drain annotations converge, node update advances.

---

## State Model
`TRIGGERED -> CONTEXT_CAPTURED -> UNIFIED_DOSSIER_COLLECTED -> ROOT_CAUSE_DIAGNOSED -> REMEDIATION_MATCHED (AAP Playbook OR Manual CLI) -> PERSISTED`

---

## Data Contract
* **Investigation Record:** `investigation_id`, `cluster_id`, `node_name`, `target_namespace`, `failing_pod`, `matching_pdb`.
* **Evidence Citations:** `mcc_eviction_error_log`, `pdb_status_snapshot`, `metric_replica_health`.
* **Remediation Specification:**
  * If automated: `{ playbook_id: "playbook_pdb_scale_up", aap_extra_vars: { ... } }`.
  * If manual: `{ manual_cli_commands: [ ... ], safety_warnings: "...", rollback_steps: "..." }`.

---

## Guardrails
- Strictly read-only execution in the diagnostic agent.
- No direct `oc patch` or `oc delete` executed autonomously.
- No weakening of PDB policy to zero without human approval.
- Secret and credential values are stripped before persistence.
