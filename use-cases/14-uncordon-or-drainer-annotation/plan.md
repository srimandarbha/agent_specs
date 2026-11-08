# Implementation Plan: Drain Annotation or Uncordon Coordination Mismatch

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Phase 0: Ground Truth & Telemetry Alignment
- [ ] Pin supported OpenShift release(s) and obtain matching MCO source/runbook revision.
- [ ] Align trigger signals in Splunk: MCC/MCD log contains `uncordon.*during update` or `desiredDrain.*lastAppliedDrain`.
- [ ] Confirm `index=ocp_logs`, `index=k8s_objects` (with `managedFields` stripped), and `index=ocp_metrics` are populated.
- [ ] Verify that Node objects and drain annotations are cached in the Splunk KV Store (`k8s_live_inventory_lookup`) for instant retrieval.

## Phase 1: Read-Only Evidence Tooling
- [ ] Implement the parameterized **Unified Multi-Index Splunk Search** (`query_unified_splunk_dossier`).
- [ ] Bound search time: `earliest=-1h latest=now` for logs/metrics; `earliest=-24h` for objects (or instant KV Store lookup).
- [ ] Normalize timestamps, cluster ID, node identity, and annotation keys into structured state.
- [ ] Redact secrets, authorization headers, and environment variables.

## Phase 2: Causal Reasoning & Classification
- [ ] Extract target node from MCC log or alert.
- [ ] Check `spec.unschedulable` and evaluate against MCO rollout phase.
- [ ] Compare `desiredDrain` with `lastAppliedDrain`.
- [ ] **Multi-level Root Cause Analysis:**
  - Has the node been uncordoned while an update is active (`spec.unschedulable == false`)?
  - Are all non-daemonset pods drained (count == 0) while `desiredDrain != lastAppliedDrain`?
  - Check for API `409 Conflict` in MCC logs when attempting to update node annotations.
  - Check whether user pods are still actively running (prohibiting annotation completion).

## Phase 3: Two-Tier Remediation & Playbook Matching
- [ ] **Catalog Matching:** Evaluate against [`remediations/PLAYBOOK_CATALOG.json`](../../remediations/PLAYBOOK_CATALOG.json):
  - If premature uncordon or annotation desync with 0 pods is verified:
    - Match `playbook_reconcile_drain_annotation`.
    - Generate `aap_extra_vars`: `{ target_cluster, draining_node, expected_mco_drain_state, action: "reconcile_and_cordon" }`.
    - Mark risk as `low` and require human approval before execution.
- [ ] **Intelligent CLI Fallback:** If live workloads are present on a node marked drained or competing controllers persist:
  - Explicitly set `playbook_match: null`.
  - Output targeted manual `oc` CLI runbook:
    ```bash
    # 1. Immediately re-cordon the node
    oc adm cordon <node>
    # 2. Check for running pods
    oc get pods -A --field-selector spec.nodeName=<node>
    # 3. Check for competing uncordon events
    oc get events -n default --field-selector involvedObject.name=<node>
    ```
- [ ] Keep all mutation tools disabled inside the agent; hand off execution to AAP or human SRE.

## Phase 4: Verification & Acceptance Tests
- [ ] Unit tests: matching trigger, non-matching trigger, incomplete evidence, and contradictory evidence.
- [ ] Graph test: single multi-index query completes within 10s; graph completes within 45s deadline.
- [ ] Playbook matching test: premature uncordon produces exact `aap_extra_vars` matching schema.
- [ ] Fallback test: live workload conflict correctly outputs emergency manual cordon runbook.
- [ ] Post-remediation verification: `desiredDrain == lastAppliedDrain`, node remains cordoned, and MCD advances.

---

## Observability & Graph Integration Contract

### Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Controller logs, Machine Config Daemon logs.
* `index=k8s_objects` / KV Store: `Node` (annotations, schedulability), `Pod` (node assignment, count), `MachineConfigPool`.
* `index=ocp_metrics`: `machine_config_pool_status_updating`, `machine_config_daemon_state`.

### Bounded Execution
* Max 2 Splunk tool calls total per investigation.
* 15-second per-query timeout; 45-second overall investigation deadline.
* Stop as `inconclusive` if cluster identity is ambiguous or required telemetry is unavailable.
