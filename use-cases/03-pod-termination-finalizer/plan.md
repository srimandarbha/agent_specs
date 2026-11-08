# Implementation Plan: Pod Remains Terminating or Finalizer Cleanup Stalls

## Phase 0: Ground Truth & Telemetry Alignment
- [ ] Pin supported OpenShift release(s) and obtain matching MCO source/runbook revision.
- [ ] Align trigger signals in Splunk: MCC log contains `error when waiting for pod ... to terminate`.
- [ ] Confirm `index=ocp_logs`, `index=k8s_objects` (with `managedFields` and secrets stripped), and `index=ocp_metrics` are populated.
- [ ] Verify that Pod and Node objects are cached in the Splunk KV Store (`k8s_live_inventory_lookup`) for instant retrieval.

## Phase 1: Read-Only Evidence Tooling
- [ ] Implement the parameterized **Unified Multi-Index Splunk Search** (`query_unified_splunk_dossier`).
- [ ] Bound search time: `earliest=-1h latest=now` for logs/metrics; `earliest=-24h` for objects (or instant KV Store lookup).
- [ ] Normalize timestamps, cluster ID, namespace, and workload names into structured state.
- [ ] Redact secrets, authorization headers, and environment variables.

## Phase 2: Causal Reasoning & Classification
- [ ] Extract failing pod and namespace from MCC log.
- [ ] Verify pod `metadata.deletionTimestamp` is set and evaluate node readiness.
- [ ] **Multi-level Root Cause Analysis:**
  - Are `metadata.finalizers` present?
    - Is it an operator finalizer? Check controlling operator health in `index=ocp_logs`.
    - Is it `kubernetes.io/pvc-protection`? Correlate VolumeAttachment in KV Store (handoff to storage use case).
  - Are finalizers empty?
    - Check if grace period has elapsed.
    - Check for `FailedKillPod` / `KillPodSandbox` events in `index=k8s_objects`.
    - Check Kubelet journal for hung preStop hooks or kernel D-state container processes.

## Phase 3: Two-Tier Remediation & Playbook Matching
- [ ] **Catalog Matching:** Evaluate against [`remediations/PLAYBOOK_CATALOG.json`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/remediations/PLAYBOOK_CATALOG.json):
  - Autonomous removal of finalizers is **strictly prohibited** (`matched: false`).
  - If storage driver RPC timeout is identified (Branch 3B), delegate to `playbook_restart_csi_driver`.
- [ ] **Intelligent CLI Fallback:**
  - For operator finalizers: generate safe operator inspection and restart commands; require human sign-off before conditional finalizer stripping.
  - For hung container processes: generate node debug session commands (`crictl ps`, `crictl stopp`, `systemctl restart crio`) under cordoned node conditions.
- [ ] Keep all mutation tools disabled inside the agent; hand off execution to AAP or human SRE.

## Phase 4: Verification & Acceptance Tests
- [ ] Unit tests: matching trigger, non-matching trigger, incomplete evidence, and contradictory evidence.
- [ ] Graph test: single multi-index query completes within 10s; graph completes within 45s deadline.
- [ ] Finalizer safety test: verify agent refuses autonomous finalizer deletion.
- [ ] Fallback test: hung CRI-O container correctly outputs node debug and crictl runbook.
- [ ] Post-remediation verification: Pod record evaporates from KV Store, no new `FailedKillPod` events, and MCC drain resumes.

---

## Observability & Graph Integration Contract

### Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Controller drain logs, Kubelet kill logs, operator controller logs.
* `index=k8s_objects` / KV Store: `Pod` (finalizers, deletionTimestamp, conditions), `Node` (Ready status), `Event` (FailedKillPod).
* `index=ocp_metrics`: `kube_pod_status_phase{phase="Terminating"}`.

### Bounded Execution
* Max 2 Splunk tool calls total per investigation.
* 15-second per-query timeout; 45-second overall investigation deadline.
* Stop as `inconclusive` if cluster identity is ambiguous or required telemetry is unavailable.
