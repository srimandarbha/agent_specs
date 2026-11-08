# Design: Stale Source Virt-Launcher Pod After Completed Migration

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Design Objective
Diagnose **stale source virt-launcher pod after completed migration**, verify that live migration has completed and the active VM is safely running on another node, and generate a deterministic remediation specification (Ansible Playbook spec or manual CLI fallback) without direct cluster mutation.

---

## Evidence-First Flow

1. **Establish Identity & Context**
   - Cluster ID, MachineConfigPool, target node, and time window.
   - Pinned OpenShift release and release-matched runbook.
2. **Confirm Lifecycle Stage**
   - Trigger signal: MCC log reports drain timeout waiting for pod `virt-launcher-*` to terminate.
   - Confirm active stage is `drain`.
3. **Execute Single Multi-Index Search**
   - Query `query_unified_splunk_dossier` spanning `index=ocp_logs`, `index=k8s_objects` / KV Store, and `index=ocp_metrics`.
4. **Causal Correlation & Classification**
   - Extract VM name from `metadata.labels['vm.kubevirt.io/name']`.
   - Query KV Store for all launcher pods for that VM across the cluster.
   - Traverse causal sub-tree:
     - Branch 3A: Healthy replacement launcher running on target node + Prometheus `kubevirt_vmi_migration_status == Succeeded`? Orphaned launcher shell.
     - Branch 3B: Dual-active processes or CPU usage on both pods? Split-brain safety halt.
     - Branch 3C: No replacement pod found? Live migration failed; handoff to `05-ocv-vm-not-migratable`.
5. **Remediation Matching**
   - Evaluate against `remediations/PLAYBOOK_CATALOG.json`.
   - If Branch 3A $\rightarrow$ generate `playbook_cleanup_stale_virt_launcher` spec with validated `extra_vars`.
   - If Branch 3B or 3C $\rightarrow$ generate targeted manual `oc` CLI fallback with strict safety checks.
6. **Persist & Verify**
   - Record investigation state and evidence IDs in PostgreSQL (`db/migrations/001_initial.sql`).
   - Monitor for recovery post-execution: Stale launcher removed, replacement launcher remains running, MCC drain resumes.

---

## State Model
`TRIGGERED -> CONTEXT_CAPTURED -> UNIFIED_DOSSIER_COLLECTED -> ROOT_CAUSE_DIAGNOSED -> REMEDIATION_MATCHED (AAP Playbook OR Manual CLI) -> PERSISTED`

---

## Data Contract
* **Investigation Record:** `investigation_id`, `cluster_id`, `node_name`, `target_namespace`, `vm_name`, `stale_pod_name`, `active_pod_name`, `target_node`.
* **Evidence Citations:** `mcc_drain_error_log`, `target_launcher_pod_snapshot`, `migration_succeeded_metric`.
* **Remediation Specification:**
  * If automated: `{ playbook_id: "playbook_cleanup_stale_virt_launcher", aap_extra_vars: { ... } }`.
  * If manual: `{ manual_cli_commands: [ ... ], safety_warnings: "...", rollback_steps: "..." }`.

---

## Guardrails
- Strictly read-only execution in the diagnostic agent.
- NEVER delete a launcher pod if only one launcher exists for the virtual machine.
- Secret and credential values are stripped before persistence.
