# Implementation Plan: Node Disk Pressure or Host Resource Exhaustion (`15-disk-pressure-host-resource`)

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Phase 0: Ground Truth & Telemetry Alignment
- [ ] Pin supported OpenShift release(s) and Kubelet eviction manager event definitions.
- [ ] Align trigger signals in Splunk: Node condition `DiskPressure: True` or `PIDPressure: True`, or Kubelet log matches `(?i)(no space left on device|ImageGCFailed|FreeDiskSpaceFailed)`.
- [ ] Verify that `Node`, `Pod`, `Event`, and `MachineConfigPool` objects are cached in the Splunk KV Store (`k8s_live_inventory_lookup`) with `managedFields` stripped.
- [ ] Confirm Prometheus metrics `node_filesystem_avail_bytes`, `node_filesystem_files_free`, and `node_pids` are indexed in `index=ocp_metrics`.

## Phase 1: Read-Only Evidence Tooling
- [ ] Implement the parameterized **Splunk logs/object evidence query** (`query_splunk_dossier`).
- [ ] Bound search time: `earliest=-1h latest=now` for logs/events/metrics; instant lookup for live KV store objects.
- [ ] Normalize timestamps, cluster ID, node name, filesystem mount points, and error excerpts into structured state.
- [ ] Redact node IP addresses and environment secrets.

## Phase 2: Causal Reasoning & Classification
- [ ] Correlate Node status conditions with Kubelet error logs and disk mount metrics.
- [ ] Classify root-cause partition or resource:
  - **Branch 3A (CRI-O Image Store):** Unpruned image layers or high pod churn filling `/var/lib/containers`.
  - **Branch 3B (Systemd Journal / Logs):** Runaway systemd journal or unrotated logs filling `/` or `/var`.
  - **Branch 3C (Pod Ephemeral Storage):** Pod writing unconstrained data to local `emptyDir` volumes on `/var/lib/kubelet`.
  - **Branch 3D (Host PID Exhaustion):** Zombie processes or thread leaks exhausting host `pids.max`.
- [ ] Exclude false positives: verify node pressure is active and has not cleared dynamically via automated Kubelet GC.

## Phase 3: Two-Tier Remediation & Playbook Matching
- [ ] **Catalog Matching:**
  - Evaluate against [`remediations/PLAYBOOK_CATALOG.json`](../../remediations/PLAYBOOK_CATALOG.json).
  - Autonomous host disk file deletion or process killing is strictly prohibited.
  - Set `playbook_match: null`.
- [ ] **Intelligent Manual CLI Fallback:**
  - Branch 3A: Output guarded CRI-O image prune commands (`oc debug node/... -- chroot /host crictl rmi --prune`).
  - Branch 3B: Output guarded systemd journal vacuum commands (`journalctl --vacuum-size=1G`).
  - Branch 3C: Output ephemeral storage inspection and unconstrained pod eviction commands.
  - Branch 3D: Output process tree audit (`systemd-cgls`) and targeted container stop commands (`crictl stop ...`).
- [ ] Ensure all fallback runbooks include explicit safety warnings against direct `rm -rf` inside overlay stores.

## Phase 4: Verification & Acceptance Tests
- [ ] Unit tests: test disk pressure error log parser against CRI-O GC failure, journal full, and PID exhaustion logs.
- [ ] Graph test: single multi-index query completes within 10s; graph completes within 45s deadline.
- [ ] Safety test: verify agent refuses autonomous file deletion or host reboot.
- [ ] Fallback test: verify generated CLI fallback includes valid `oc debug node` commands and runtime pruning steps.
- [ ] Post-remediation verification: target node reports `DiskPressure: False`, `PIDPressure: False`, node condition `Ready: True`, and MCD transitions to `Done`.

---

## Observability & Graph Integration Contract

### Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Kubelet GC error logs, MCD configuration write error logs, and systemd journal logs.
* `index=k8s_objects` / KV Store: `Node` (conditions `DiskPressure`, `PIDPressure`), `Pod`, `Event`, and `MachineConfigPool`.
* `index=ocp_metrics`: Filesystem available bytes, inode availability, and host PID count.

### Bounded Execution
* Max 2 Splunk tool calls total per investigation.
* 15-second per-query timeout; 45-second overall investigation deadline.
* Stop as `inconclusive` if cluster identity is ambiguous or required telemetry is unavailable.
