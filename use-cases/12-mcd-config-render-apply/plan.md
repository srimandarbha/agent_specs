# Implementation Plan: Rendered MachineConfig or Configuration Apply Failure

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Phase 0: Ground Truth & Telemetry Alignment
- [ ] Pin supported OpenShift release(s) and obtain matching MCO source/runbook revision.
- [ ] Align trigger signals in Splunk: MCP `RenderDegraded: True` or MCD logs report `failed to apply update`.
- [ ] Confirm `index=ocp_logs`, `index=k8s_objects` (with `managedFields` stripped), and `index=ocp_metrics` (`machine_config_pool_status_degraded`) are populated.
- [ ] Verify that `MachineConfigPool` and `Node` objects are cached in the Splunk KV Store (`k8s_live_inventory_lookup`) for instant retrieval.

## Phase 1: Read-Only Evidence Tooling
- [ ] Implement the parameterized **Unified Multi-Index Splunk Search** (`query_unified_splunk_dossier`).
- [ ] Bound search time: `earliest=-1h latest=now` for logs/metrics; `earliest=-24h` for objects (or instant KV Store lookup).
- [ ] Normalize timestamps, cluster ID, pool identity, and conflicting file paths into structured state.
- [ ] Redact secrets, authorization headers, and environment variables.

## Phase 2: Causal Reasoning & Classification
- [ ] Extract target pool or node from MCC/MCD logs.
- [ ] Distinguish render-time errors (MCC) from apply-time errors (MCD).
- [ ] **Multi-level Root Cause Analysis:**
  - Are multiple custom MachineConfigs colliding on a single file path?
  - Has MCD failed writing files on host due to disk space exhaustion or permission errors?
  - Is there an incompatible Ignition specification version?

## Phase 3: Two-Tier Remediation & Playbook Matching
- [ ] **Catalog Matching:** Evaluate against [`remediations/PLAYBOOK_CATALOG.json`](../../remediations/PLAYBOOK_CATALOG.json):
  - Autonomous mutation of MachineConfigs is **strictly prohibited** (`matched: false`).
- [ ] **Intelligent CLI Fallback:**
  - For render conflicts: output runbook to locate colliding MachineConfigs and reconcile in GitOps.
  - For apply failures: output host disk inspection and systemd unit troubleshooting commands.
- [ ] Keep all mutation tools disabled inside the agent; hand off execution to human SRE and platform administrators.

## Phase 4: Verification & Acceptance Tests
- [ ] Unit tests: matching trigger, non-matching trigger, incomplete evidence, and contradictory evidence.
- [ ] Graph test: single multi-index query completes within 10s; graph completes within 45s deadline.
- [ ] Safety test: verify agent strictly refuses direct patching of `rendered-*` MachineConfigs.
- [ ] Fallback test: conflicting MachineConfigs correctly outputs `jq` extraction runbook.
- [ ] Post-remediation verification: `RenderDegraded` clears, node state becomes `Done`, and `currentConfig == desiredConfig`.

---

## Observability & Graph Integration Contract

### Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Controller render logs, Machine Config Daemon apply logs.
* `index=k8s_objects` / KV Store: `MachineConfigPool` (conditions, config hashes), `Node` (annotations, state).
* `index=ocp_metrics`: `machine_config_pool_status_degraded`, `machine_config_daemon_state`.

### Bounded Execution
* Max 2 Splunk tool calls total per investigation.
* 15-second per-query timeout; 45-second overall investigation deadline.
* Stop as `inconclusive` if cluster identity is ambiguous or required telemetry is unavailable.
