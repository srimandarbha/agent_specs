# Design: MachineConfigPool Paused or Rollout Coordination Prevents Progress

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Design Objective
Diagnose **mcp paused or rollout coordination prevents progress**, determine whether the pause is an intentional administrative hold ready to be resumed, an expected concurrency throttle, or a critical degraded safety interlock, and generate a deterministic remediation specification (Ansible Playbook spec or manual CLI fallback) without direct cluster mutation.

---

## Evidence-First Flow

1. **Establish Identity & Context**
   - Cluster ID, target MachineConfigPool, and time window.
   - Pinned OpenShift release and release-matched runbook.
2. **Confirm Lifecycle Stage**
   - Trigger signal: MCP reports `spec.paused == true` or rollout does not begin.
   - Confirm active stage is `rollout-coordination`.
3. **Execute Single Multi-Index Search**
   - Query `query_unified_splunk_dossier` spanning `index=ocp_logs`, `index=k8s_objects` / KV Store, and `index=ocp_metrics`.
4. **Causal Correlation & Classification**
   - Retrieve `MachineConfigPool` status from KV Store.
   - Traverse causal sub-tree:
     - Branch 3A: `spec.paused == true`, `Degraded == False`, nodes healthy? Stale administrative pause.
     - Branch 3B: `spec.paused == false`, `unavailableMachineCount >= maxUnavailable`? Normal rollout serialization.
     - Branch 3C: `spec.paused == true`, `Degraded == True`? Safety interlock on corrupted configuration.
5. **Remediation Matching**
   - Evaluate against `remediations/PLAYBOOK_CATALOG.json`.
   - If Branch 3A $\rightarrow$ generate `playbook_unpause_mcp` spec with validated `extra_vars`.
   - If Branch 3B $\rightarrow$ report normal serialization (`not_supported`).
   - If Branch 3C $\rightarrow$ generate targeted manual `oc` CLI fallback with strict safety interlock.
6. **Persist & Verify**
   - Record investigation state and evidence IDs in PostgreSQL (`db/migrations/001_initial.sql`).
   - Monitor for recovery post-execution: MCP unpaused, `Updating` condition set to True, nodes initiate update.

---

## State Model
`TRIGGERED -> CONTEXT_CAPTURED -> UNIFIED_DOSSIER_COLLECTED -> ROOT_CAUSE_DIAGNOSED -> REMEDIATION_MATCHED (AAP Playbook OR Manual CLI) -> PERSISTED`

---

## Data Contract
* **Investigation Record:** `investigation_id`, `cluster_id`, `mcp_name`, `is_paused`, `is_degraded`, `unavailable_count`, `max_unavailable`.
* **Evidence Citations:** `mcp_status_snapshot`, `node_readiness_counts`, `mcc_log_excerpt`.
* **Remediation Specification:**
  * If automated: `{ playbook_id: "playbook_unpause_mcp", aap_extra_vars: { ... } }`.
  * If manual: `{ manual_cli_commands: [ ... ], safety_warnings: "...", rollback_steps: "..." }`.

---

## Guardrails
- Strictly read-only execution in the diagnostic agent.
- NEVER unpause a `Degraded` MachineConfigPool.
- Secret and credential values are stripped before persistence.
