# Design: Rendered MachineConfig or Configuration Apply Failure

## Design Objective
Diagnose **rendered machineconfig or configuration application failure**, isolate whether the breakdown is a render-time merge collision between custom MachineConfigs or a node-level file-write/systemd-reload failure in MCD, and generate a deterministic manual CLI fallback specification without direct cluster mutation.

---

## Evidence-First Flow

1. **Establish Identity & Context**
   - Cluster ID, MachineConfigPool, target node, and time window.
   - Pinned OpenShift release and release-matched runbook.
2. **Confirm Lifecycle Stage**
   - Trigger signal: MCP reports `RenderDegraded` or Node reports apply error in MCD.
   - Confirm active stage is `config-render` or `config-apply`.
3. **Execute Single Multi-Index Search**
   - Query `query_unified_splunk_dossier` spanning `index=ocp_logs`, `index=k8s_objects` / KV Store, and `index=ocp_metrics`.
4. **Causal Correlation & Classification**
   - Inspect MCP `status.conditions` (`RenderDegraded`, `Degraded`).
   - Retrieve Node annotations `state` and `reason` from KV Store.
   - Traverse causal sub-tree:
     - Branch 3A: `RenderDegraded == True`? MachineConfig duplicate file path collision.
     - Branch 3B: `state == "Degraded"` on node during apply? Host disk full, permission denied, or systemd reload error.
     - Branch 3C: MCC logs report schema parse error? Invalid Ignition version or malformed YAML.
5. **Remediation Matching**
   - Automated remediation strictly prohibited (`matched: false`).
   - Generate targeted manual `oc` CLI fallback with GitOps reconciliation guidance or host disk cleanup steps.
6. **Persist & Verify**
   - Record investigation state and evidence IDs in PostgreSQL (`db/migrations/001_initial.sql`).
   - Monitor for recovery post-execution: RenderDegraded clears, node applies config, state returns to `Done`.

---

## State Model
`TRIGGERED -> CONTEXT_CAPTURED -> UNIFIED_DOSSIER_COLLECTED -> ROOT_CAUSE_DIAGNOSED -> REMEDIATION_MATCHED (Manual CLI Fallback) -> PERSISTED`

---

## Data Contract
* **Investigation Record:** `investigation_id`, `cluster_id`, `pool_name`, `node_name`, `is_render_degraded`, `conflicting_path`, `failed_service`.
* **Evidence Citations:** `mcc_render_error_log`, `mcd_apply_error_log`, `node_degraded_annotation`.
* **Remediation Specification:**
  * `{ manual_cli_commands: [ ... ], safety_warnings: "...", rollback_steps: "..." }`.

---

## Guardrails
- Strictly read-only execution in the diagnostic agent.
- NEVER edit generated `rendered-<pool>-<hash>` MachineConfigs directly.
- Secret and credential values are stripped before persistence.
