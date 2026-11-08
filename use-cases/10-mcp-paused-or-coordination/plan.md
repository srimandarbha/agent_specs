# Implementation Plan: MachineConfigPool Paused or Rollout Coordination Prevents Progress

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Phase 0: Ground Truth & Telemetry Alignment
- [ ] Pin supported OpenShift release(s) and obtain matching MCO source/runbook revision.
- [ ] Align trigger signals in Splunk: MCP `spec.paused == true` or MCC logs report `pool is paused, not updating`.
- [ ] Confirm `index=ocp_logs`, `index=k8s_objects` (with `managedFields` stripped), and `index=ocp_metrics` are populated.
- [ ] Verify that `MachineConfigPool` and `Node` objects are cached in the Splunk KV Store (`k8s_live_inventory_lookup`) for instant retrieval.

## Phase 1: Read-Only Evidence Tooling
- [ ] Implement the parameterized **Unified Multi-Index Splunk Search** (`query_unified_splunk_dossier`).
- [ ] Bound search time: `earliest=-1h latest=now` for logs/metrics; `earliest=-24h` for objects (or instant KV Store lookup).
- [ ] Normalize timestamps, cluster ID, pool identity, and counts into structured state.
- [ ] Redact secrets, authorization headers, and environment variables.

## Phase 2: Causal Reasoning & Classification
- [ ] Extract target pool from MCC log or alert.
- [ ] Inspect `spec.paused`, `spec.maxUnavailable`, and `status.conditions`.
- [ ] **Multi-level Root Cause Analysis:**
  - Is `spec.paused == true` while the pool is healthy and not degraded?
  - Is `spec.paused == false` but `unavailableMachineCount >= maxUnavailable` (normal concurrency serialization)?
  - Is the pool paused because it is in a `Degraded` state (safety interlock)?

## Phase 3: Two-Tier Remediation & Playbook Matching
- [ ] **Catalog Matching:** Evaluate against [`remediations/PLAYBOOK_CATALOG.json`](../../remediations/PLAYBOOK_CATALOG.json):
  - If clean administrative pause is confirmed and all nodes in the pool are healthy:
    - Match `playbook_unpause_mcp`.
    - Generate `aap_extra_vars`: `{ target_cluster, target_mcp_name }`.
    - Mark risk as `medium` and require human approval before execution.
- [ ] **Intelligent CLI Fallback:** If pool is degraded or contains unhealthy nodes:
  - Explicitly set `playbook_match: null`.
  - Output targeted manual `oc` CLI runbook:
    ```bash
    # 1. Inspect degraded pool conditions
    oc describe mcp <target_mcp_name>
    # 2. Check controller logs for config errors
    oc -n openshift-machine-config-operator logs deployment/machine-config-controller -c machine-config-controller | grep -Ei 'degraded|render|error'
    # 3. Only unpause after resolving degradation
    oc patch mcp <target_mcp_name> --type=merge -p '{"spec":{"paused":false}}'
    ```
- [ ] Keep all mutation tools disabled inside the agent; hand off execution to AAP or human SRE.

## Phase 4: Verification & Acceptance Tests
- [ ] Unit tests: matching trigger, non-matching trigger, incomplete evidence, and contradictory evidence.
- [ ] Graph test: single multi-index query completes within 10s; graph completes within 45s deadline.
- [ ] Playbook matching test: valid paused pool produces exact `aap_extra_vars` matching schema.
- [ ] Concurrency limit test: normal `maxUnavailable` throttling correctly reports `not_supported` without remediation.
- [ ] Safety test: degraded pool strictly prohibits unpausing.
- [ ] Post-remediation verification: `spec.paused == false`, `Updating == True`, and rollout resumes.

---

## Observability & Graph Integration Contract

### Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Controller rollout logs.
* `index=k8s_objects` / KV Store: `MachineConfigPool` (spec/status, conditions, counters), `Node` (readiness).
* `index=ocp_metrics`: `machine_config_pool_status_paused`, `machine_config_pool_status_updating`, `machine_config_pool_status_degraded`.

### Bounded Execution
* Max 2 Splunk tool calls total per investigation.
* 15-second per-query timeout; 45-second overall investigation deadline.
* Stop as `inconclusive` if cluster identity is ambiguous or required telemetry is unavailable.
