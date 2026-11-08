# Implementation Plan: Storage Unmount or Detach Stalls Pod Termination

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Phase 0: Ground Truth & Telemetry Alignment
- [ ] Pin supported OpenShift release(s) and storage CSI driver versions (e.g. ODF/Ceph RBD, AWS EBS, Azure Disk, VMware vSphere).
- [ ] Align trigger signals in Splunk: Kubelet or CSI logs match `(?i)(failed to unmount|unmountdevice failed|failed to detach|volume.*still attached|volumeattachment.*in use|device or resource busy)`.
- [ ] Confirm `VolumeAttachment` objects are collected without `managedFields` and cached in Splunk KV Store (`k8s_live_inventory_lookup`).

## Phase 1: Read-Only Evidence Tooling
- [ ] Implement the parameterized **Splunk logs/object evidence query** (`query_splunk_dossier`).
- [ ] Bound search time: `earliest=-1h latest=now` for logs/metrics; `earliest=-24h` for objects (or instant KV Store lookup).
- [ ] Extract VolumeAttachment status (`attached`, `detachError`) and Kubelet unmount logs.
- [ ] Redact credentials, tokens, and storage backend authentication details.

## Phase 2: Causal Reasoning & Classification
- [ ] Extract failing pod, namespace, and volume name from Kubelet logs.
- [ ] Look up VolumeAttachment for the node and volume in `k8s_objects` / KV Store.
- [ ] **Multi-level Root Cause Analysis:**
  - Branch A: Is the local CSI node daemonset pod hung (RPC `DeadlineExceeded`)?
  - Branch B: Is it a storage array / cloud multi-attach conflict (`Multi-Attach error`)?
  - Branch C: Is a host process holding open file descriptors on the mount (`device or resource busy`)?

## Phase 3: Two-Tier Remediation & Playbook Matching
- [ ] **Catalog Matching:** Evaluate against [`remediations/PLAYBOOK_CATALOG.json`](../../remediations/PLAYBOOK_CATALOG.json):
  - If Branch A (local CSI node daemon hang):
    - Match `playbook_restart_csi_driver`.
    - Generate `aap_extra_vars`: `{ target_cluster, draining_node, csi_driver_namespace, csi_driver_daemonset }`.
    - Mark risk as `low` and require human approval before execution.
- [ ] **Intelligent CLI Fallback:** If Branch B (multi-attach lock) or Branch C (device busy):
  - Explicitly set `playbook_match: null`.
  - Output targeted manual `oc` CLI runbook:
    ```bash
    # 1. Check VolumeAttachment status:
    oc get volumeattachment | grep <volume_name>
    # 2. Inspect CSI controller logs:
    oc -n <csi_ns> logs deployment/<csi_controller> -c csi-driver --tail=50
    # 3. Check open file descriptors on host:
    oc adm node-logs <node> --path=journal | grep -Ei 'umount.*busy|<volume_name>'
    ```
- [ ] Enforce safety: NEVER delete `VolumeAttachment` directly while a process is writing to the disk.

## Phase 4: Verification & Acceptance Tests
- [ ] Unit tests: matching unmount error, non-matching trigger, incomplete evidence, and conflicting evidence.
- [ ] Graph test: single multi-index query completes within 10s; graph completes within 45s deadline.
- [ ] Playbook matching test: local CSI daemon hang produces exact `aap_extra_vars`.
- [ ] Fallback test: multi-attach conflict correctly routes to manual CLI runbook with data corruption warnings.
- [ ] Post-remediation verification: `VolumeAttachment.status.attached == false`, pod terminates, and MCO drain advances.

---

## Observability & Graph Integration Contract

### Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Kubelet unmount logs and CSI driver container logs.
* `index=k8s_objects` / KV Store: `Pod` (`spec.volumes`, `metadata.deletionTimestamp`), `VolumeAttachment` (`spec.nodeName`, `status.attached`, `status.detachError`), `Node` (cordon status).
* `index=ocp_metrics`: Storage I/O metrics and node filesystem utilization.

### Bounded Execution
* Max 2 Splunk tool calls total per investigation.
* 15-second per-query timeout; 45-second overall investigation deadline.
* Stop as `inconclusive` if cluster identity is ambiguous or required telemetry is unavailable.
