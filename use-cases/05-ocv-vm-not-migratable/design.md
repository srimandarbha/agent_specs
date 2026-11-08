# Design: OpenShift Virtualization VM Is Not Live-Migratable

## Design Objective
Diagnose **openshift virtualization vm is not live-migratable**, isolate whether the migration blocker is non-shared local storage, host PCI/GPU hardware binding, or destination node capacity exhaustion, and generate a deterministic manual CLI fallback specification without direct cluster mutation.

---

## Evidence-First Flow

1. **Establish Identity & Context**
   - Cluster ID, MachineConfigPool, target node, and time window.
   - Pinned OpenShift release and release-matched runbook.
2. **Confirm Lifecycle Stage**
   - Trigger signal: MCC log contains eviction denial from `virt-launcher-eviction-interceptor.kubevirt.io`.
   - Confirm active stage is `drain`.
3. **Execute Single Multi-Index Search**
   - Query `query_unified_splunk_dossier` spanning `index=ocp_logs`, `index=k8s_objects` / KV Store, and `index=ocp_metrics`.
4. **Causal Correlation & Classification**
   - Extract VM name from `virt-launcher` pod labels.
   - Correlate with Prometheus metric `kubevirt_vmi_non_evictable`.
   - Traverse causal sub-tree:
     - Branch 3A: `reason="DisksNotMigratable"`? Local / RWO storage constraint.
     - Branch 3B: `reason="HostDevicesNotMigratable"`? Pinned GPU / PCI hardware.
     - Branch 3C: `kubevirt_vmi_migration_status{status="failed"}` with scheduling errors? Target node capacity deadlock.
5. **Remediation Matching**
   - Automated remediation strictly prohibited.
   - Generate targeted manual `oc` CLI fallback with options for planned guest shutdown, storage migration, or temporary eviction strategy modification.
6. **Persist & Verify**
   - Record investigation state and evidence IDs in PostgreSQL (`db/migrations/001_initial.sql`).
   - Monitor for recovery post-execution: Launcher pod removed from draining node, MCC drain resumes.

---

## State Model
`TRIGGERED -> CONTEXT_CAPTURED -> UNIFIED_DOSSIER_COLLECTED -> ROOT_CAUSE_DIAGNOSED -> REMEDIATION_MATCHED (Manual CLI Fallback) -> PERSISTED`

---

## Data Contract
* **Investigation Record:** `investigation_id`, `cluster_id`, `node_name`, `target_namespace`, `vm_name`, `non_evictable_reason`.
* **Evidence Citations:** `mcc_eviction_interceptor_log`, `vmi_non_evictable_metric`, `pod_storage_binding`.
* **Remediation Specification:**
  * `{ manual_cli_commands: [ ... ], safety_warnings: "...", rollback_steps: "..." }`.

---

## Guardrails
- Strictly read-only execution in the diagnostic agent.
- No direct `virtctl stop` or `oc patch vm` executed autonomously.
- Secret and credential values are stripped before persistence.
