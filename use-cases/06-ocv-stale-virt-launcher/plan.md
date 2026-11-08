# Implementation Plan: Stale Source Virt-Launcher Pod After Completed Migration

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Phase 0: Ground Truth & Telemetry Alignment
- [ ] Pin supported OpenShift release(s) and obtain matching MCO source/runbook revision.
- [ ] Align trigger signals in Splunk: MCC log contains `error when waiting for pod ... virt-launcher.*to terminate`.
- [ ] Confirm `index=ocp_logs`, `index=k8s_objects` (with `managedFields` stripped), and `index=ocp_metrics` are populated.
- [ ] Verify that Pod objects (with `vm.kubevirt.io/name` labels) and Nodes are cached in the Splunk KV Store (`k8s_live_inventory_lookup`) for instant retrieval.

## Phase 1: Read-Only Evidence Tooling
- [ ] Implement the parameterized **Unified Multi-Index Splunk Search** (`query_unified_splunk_dossier`).
- [ ] Bound search time: `earliest=-1h latest=now` for logs/metrics; `earliest=-24h` for objects (or instant KV Store lookup).
- [ ] Normalize timestamps, cluster ID, VM name, and launcher pod names into structured state.
- [ ] Redact secrets, authorization headers, and environment variables.

## Phase 2: Causal Reasoning & Classification
- [ ] Extract failing pod and namespace from MCC log.
- [ ] Extract VM name from pod labels (`vm.kubevirt.io/name`).
- [ ] Query for all launcher pods belonging to that VM across the cluster.
- [ ] **Multi-level Root Cause Analysis:**
  - Is there a replacement launcher pod running on a different node in `phase: Running`?
  - Does Prometheus metric `kubevirt_vmi_migration_status{status="succeeded"}` confirm completed migration?
  - Check for dual-active CPU consumption (split-brain danger).
  - If no replacement pod is found, route immediately to `05-ocv-vm-not-migratable`.

## Phase 3: Two-Tier Remediation & Playbook Matching
- [ ] **Catalog Matching:** Evaluate against [`remediations/PLAYBOOK_CATALOG.json`](../../remediations/PLAYBOOK_CATALOG.json):
  - If replacement pod is healthy on target node and migration succeeded:
    - Match `playbook_cleanup_stale_virt_launcher`.
    - Generate `aap_extra_vars`: `{ target_cluster, vmi_namespace, vmi_name, stale_pod_name, draining_node }`.
    - Mark risk as `medium` and require human approval before execution.
- [ ] **Intelligent CLI Fallback:** If migration status is ambiguous or dual-active risk detected:
  - Explicitly set `playbook_match: null`.
  - Output targeted manual `oc` CLI runbook:
    ```bash
    # 1. Verify VM migration status
    oc get vmi <vm_name> -n <namespace> -o wide
    # 2. Check both launcher pods
    oc get pods -n <namespace> -l vm.kubevirt.io/name=<vm_name> -o wide
    # 3. Only delete stale pod after confirming traffic on target node
    oc delete pod <stale_pod_name> -n <namespace> --grace-period=30
    ```
- [ ] Keep all mutation tools disabled inside the agent; hand off execution to AAP or human SRE.

## Phase 4: Verification & Acceptance Tests
- [ ] Unit tests: matching trigger, non-matching trigger, incomplete evidence, and contradictory evidence.
- [ ] Graph test: single multi-index query completes within 10s; graph completes within 45s deadline.
- [ ] Playbook matching test: confirmed stale launcher produces exact `aap_extra_vars` matching schema.
- [ ] Fallback test: un-migrated VM launcher correctly routes to 05 and strictly refuses pod deletion.
- [ ] Post-remediation verification: Stale launcher removed, replacement launcher remains running, and MCC resumes drain.

---

## Observability & Graph Integration Contract

### Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Controller drain logs, virt-handler logs.
* `index=k8s_objects` / KV Store: `Pod` (labels, phase, node assignment), `Node` (cordon status).
* `index=ocp_metrics`: `kubevirt_vmi_migration_status{status="succeeded"}`, `kubevirt_vmi_phase_count`.

### Bounded Execution
* Max 2 Splunk tool calls total per investigation.
* 15-second per-query timeout; 45-second overall investigation deadline.
* Stop as `inconclusive` if cluster identity is ambiguous or required telemetry is unavailable.
