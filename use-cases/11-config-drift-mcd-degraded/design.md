# Design: Machine Config Daemon Configuration Drift

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Design Objective
Diagnose **machine config daemon reports configuration drift**, determine whether the drift is due to a failed auxiliary service, out-of-band file mutation in `/etc`, or immutable OS corruption, and generate a deterministic remediation specification (Ansible Playbook spec or manual CLI fallback) without direct cluster mutation.

---

## Evidence-First Flow

1. **Establish Identity & Context**
   - Cluster ID, MachineConfigPool, target node, and time window.
   - Pinned OpenShift release and release-matched runbook.
2. **Confirm Lifecycle Stage**
   - Trigger signal: Node annotation `state` is `Degraded` or MCD logs report config drift.
   - Confirm active stage is `preflight` or `apply`.
3. **Execute Single Multi-Index Search**
   - Query `query_unified_splunk_dossier` spanning `index=ocp_logs`, `index=k8s_objects` / KV Store, and `index=ocp_metrics`.
4. **Causal Correlation & Classification**
   - Match drifted file path or unit from MCD logs.
   - Retrieve Node `state` and `reason` annotations from KV Store.
   - Traverse causal sub-tree:
     - Branch 3A: Drifted target is an allowlisted systemd unit? Recoverable service crash.
     - Branch 3B: Drifted target is an MCO-managed file in `/etc`? Out-of-band edit.
     - Branch 3C: Drifted target is in `/usr` or ostree image? OS corruption.
5. **Remediation Matching**
   - Evaluate against `remediations/PLAYBOOK_CATALOG.json`.
   - If Branch 3A $\rightarrow$ generate `playbook_restart_failed_systemd_unit` spec with validated `extra_vars`.
   - If Branch 3B or 3C $\rightarrow$ generate targeted manual `oc` CLI fallback with diff comparison and safe forcefile steps.
6. **Persist & Verify**
   - Record investigation state and evidence IDs in PostgreSQL (`db/migrations/001_initial.sql`).
   - Monitor for recovery post-execution: Node state returns to `Done`, MCP degraded flag clears.

---

## State Model
`TRIGGERED -> CONTEXT_CAPTURED -> UNIFIED_DOSSIER_COLLECTED -> ROOT_CAUSE_DIAGNOSED -> REMEDIATION_MATCHED (AAP Playbook OR Manual CLI) -> PERSISTED`

---

## Data Contract
* **Investigation Record:** `investigation_id`, `cluster_id`, `node_name`, `drifted_filepath`, `current_config`, `desired_config`.
* **Evidence Citations:** `mcd_drift_log_excerpt`, `node_degraded_annotation`, `mcp_degraded_status`.
* **Remediation Specification:**
  * If automated: `{ playbook_id: "playbook_restart_failed_systemd_unit", aap_extra_vars: { ... } }`.
  * If manual: `{ manual_cli_commands: [ ... ], safety_warnings: "...", rollback_steps: "..." }`.

---

## Guardrails
- Strictly read-only execution in the diagnostic agent.
- NEVER create `/run/machine-config-daemon-force` autonomously.
- Secret and credential values are stripped before persistence.
