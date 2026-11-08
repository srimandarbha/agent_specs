# Implementation Plan: PodDisruptionBudget Blocks Eviction

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Phase 0: Ground Truth & Telemetry Alignment
- [ ] Pin supported OpenShift release(s) and obtain matching MCO source/runbook revision.
- [ ] Align trigger signals in Splunk: MCC log contains `Cannot evict pod ... as it would violate the pod's disruption budget`.
- [ ] Confirm `index=ocp_logs`, `index=k8s_objects` (with `managedFields` stripped), and `index=ocp_metrics` are populated.
- [ ] Verify that PDBs and Pods are cached in the Splunk KV Store (`k8s_live_inventory_lookup`) for zero-compute retrieval.

## Phase 1: Read-Only Evidence Tooling
- [ ] Implement the parameterized **Splunk logs/object evidence query** (`query_splunk_dossier`).
- [ ] Bound search time: `earliest=-1h latest=now` for logs/metrics; `earliest=-24h` for objects (or instant KV Store lookup).
- [ ] Normalize timestamps, cluster ID, namespace, and workload names into structured state.
- [ ] Redact secrets, authorization headers, and environment variables.

## Phase 2: Causal Reasoning & Classification
- [ ] Extract failing pod and namespace from MCC log.
- [ ] Match PDB label selectors against pod labels in `target_namespace`.
- [ ] Evaluate PDB `status.disruptionsAllowed` (must be 0 at the failure timestamp).
- [ ] **Multi-level Root Cause Analysis:** Diagnose *why* disruptions are blocked:
  - Is a sibling replica unready/crashing (`kube_pod_container_status_waiting_reason`)?
  - Is the workload a single-replica service with `minAvailable: 1`?
  - Is cluster capacity exhausted preventing replacement pods from scheduling?

## Phase 3: Two-Tier Remediation & Playbook Matching
- [ ] **Catalog Matching:** Evaluate against [`remediations/PLAYBOOK_CATALOG.json`](../../remediations/PLAYBOOK_CATALOG.json):
  - If a multi-replica Deployment/StatefulSet is at `minAvailable` and cluster capacity exists:
    - Match `playbook_pdb_scale_up`.
    - Generate `aap_extra_vars`: `{ target_cluster, target_namespace, workload_kind, workload_name, target_pdb_name, current_replicas, scale_to: current_replicas + 1 }`.
    - Mark risk as `low` and require human approval before execution.
- [ ] **Intelligent CLI Fallback:** If single-replica, unmanaged pod, or capacity-constrained:
  - Explicitly set `playbook_match: null`.
  - Output targeted manual `oc` CLI runbook:
    ```bash
    # 1. Inspect sibling pods
    oc get pods -n <namespace> -l <selector>
    # 2. Scale deployment or investigate crash
    oc scale deployment <deployment> -n <namespace> --replicas=<N+1>
    # 3. Verify PDB allows disruption
    oc get pdb <pdb> -n <namespace>
    ```
- [ ] Keep all mutation tools disabled inside the agent; hand off execution to AAP or human SRE.

## Phase 4: Verification & Acceptance Tests
- [ ] Unit tests: matching trigger, non-matching trigger, incomplete evidence, and contradictory evidence.
- [ ] Graph test: single multi-index query completes within 10s; graph completes within 45s deadline.
- [ ] Playbook matching test: valid PDB stall produces exact `aap_extra_vars` matching schema.
- [ ] Fallback test: unmanaged pod stall correctly outputs manual CLI runbook with rollback instructions.
- [ ] Post-remediation verification: MCC logs confirm blocker pod evicted, desired/last-applied drainer annotations converge, and pool advances.

---

## Observability & Graph Integration Contract

### Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Controller eviction logs and Kubelet teardown logs.
* `index=k8s_objects` / KV Store: `Pod` (labels, finalizers, phase) and `PodDisruptionBudget` (`spec.selector`, `disruptionsAllowed`).
* `index=ocp_metrics`: `kube_pod_disruption_budget_status_pod_disruptions_allowed`, `kube_pod_container_status_waiting_reason`.

### Bounded Execution
* Max 2 Splunk tool calls total per investigation.
* 15-second per-query timeout; 45-second overall investigation deadline.
* Stop as `inconclusive` if cluster identity is ambiguous or required telemetry is unavailable.
