# SPEC: Node Disk Pressure or Host Resource Exhaustion (`15-disk-pressure-host-resource`)

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Problem Statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **node disk pressure, ephemeral storage saturation, or host process (PID) exhaustion**, isolate the specific partition or subsystem facing starvation (CRI-O container image store, host systemd journal / audit logs, pod emptyDir ephemeral storage, or host PID table), and generate a guarded manual CLI fallback runbook using evidence from Splunk without direct Kubernetes cluster mutation.

## Trigger and Scope
- **Lifecycle Stage:** **Node Drain / MCD Apply / Node Readiness**
- **Trigger Signal:** Node condition `DiskPressure: True` or `PIDPressure: True` in `index=k8s_objects` OR Kubelet/MCD logs in `index=ocp_logs` match:
  `(?i)(no space left on device|FreeDiskSpaceFailed|ImageGCFailed|failed to garbage collect images|eviction manager: node had condition: \[DiskPressure\]|maximum number of pids reached|write /etc/.*: no space left on device)`.
- **In Scope:** Read-only evidence gathering from unified Splunk multi-index search/KV store, root-cause isolation across host subsystems, confidence reporting, remediation formulation (Manual CLI fallback with strict safety guardrails), and recovery verification.
- **Out of Scope:** Autonomous host file deletion, arbitrary `rm -rf` inside container directories, killing core platform daemons, or direct cluster mutation.

## Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`:
  * Kubelet logs on target node: `ImageGCFailed`, `FreeDiskSpaceFailed`, `eviction manager` disk/PID pressure declarations.
  * MCD logs: `write /etc/...: no space left on device`, config render/apply write failures.
* `index=k8s_objects` / KV Store:
  * `Node`: Target node `status.conditions` (`DiskPressure`, `PIDPressure`, `Ready`), allocatable/capacity storage, and daemon lease status.
  * `Pod`: Workload pods on target node with unconstrained ephemeral storage or evictions.
  * `Event`: `reason IN ["Evicted", "FailedScheduling", "NodeDiskPressure", "FreeDiskSpaceFailed"]`.
  * `MachineConfigPool`: Pool status reporting `Degraded: True` or `Updating` stalled.
* `index=ocp_metrics`:
  * `node_filesystem_avail_bytes{mountpoint=~"/|/var|/var/lib/containers"}`, `node_filesystem_size_bytes`.
  * `node_filesystem_files_free` (inode exhaustion).
  * `node_pids{node="<node>"}`, `node_pids_max`.

## Diagnostic Strategy
1. **Perception:** Ingest unified Splunk dossier in a single round-trip (< 10s query, < 45s deadline).
2. **Correlation:** Match the node under maintenance with active `DiskPressure` or `PIDPressure` conditions and correlate with MCD write errors or Kubelet eviction manager logs.
3. **Causal Branching:**
   - **Branch 3A (CRI-O Image Store Exhaustion):** `/var/lib/containers` > 85% full, Kubelet logs report `ImageGCFailed` or `failed to garbage collect images`.
   - **Branch 3B (Host Systemd Journal / Log Exhaustion):** `/` or `/var` > 95% full, `/var/log/journal` consuming excessive disk, MCD reports `no space left on device`.
   - **Branch 3C (Pod Ephemeral Storage Bloat):** Pod writing unconstrained data to local `emptyDir` on `/var/lib/kubelet` without `limits.ephemeral-storage`.
   - **Branch 3D (Host PID Table Exhaustion):** Node condition `PIDPressure: True`, `node_pids` approaching `kernel.pid_max`, process spawn failures.

## Two-Tier Remediation Contract
Host disk and process cleanup carries catastrophic data-loss and state-corruption risks. Autonomous mutation is strictly prohibited.
- **Ansible Playbook Catalog:** `playbook_match: null`. (No automated playbook is permitted to delete host files or kill processes autonomously).
- **Targeted Manual CLI Fallback:**
  - *Branch 3A (Image Store):* Guarded SRE procedure to debug node and execute `crictl rmi --prune` via runtime socket (avoiding direct overlay2 filesystem tampering).
  - *Branch 3B (Journal):* Guarded SRE procedure to vacuum systemd logs (`journalctl --vacuum-size=1G`).
  - *Branch 3C (Ephemeral Storage):* Procedure to inspect pod usage (`du -sh /var/lib/kubelet/pods/...`) and evict offending unconstrained workloads.
  - *Branch 3D (PID Exhaustion):* Procedure to inspect cgroups (`systemd-cgls`) and terminate the offending container via `crictl stop`.

## Safety Constraints
> [!CAUTION]
> The diagnostic agent MUST NEVER recommend or execute recursive file deletion (`rm -rf`) under `/var/lib/containers/storage/overlay` or `/var/lib/kubelet`. Deleting files directly from backing stores breaks overlay2 metadata and corrupts the CRI-O database, bricking the node.

## Success Criteria
1. Node condition `DiskPressure: False` and `PIDPressure: False`.
2. Target node condition `Ready: True`.
3. MCD pod on target node applies configuration without I/O write failures and transitions to `Done`.
4. MachineConfigPool update advances to next node.

---

## Agent Graph Integration Contract

This use case is invoked by the shared 10-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`.

### Bounded Execution
* Investigation Deadline: 45 seconds.
* Tool Budget: Max 2 Splunk tool calls per investigation.
* Output: Structured report with evidence citations, root-cause partition isolation, and guarded manual CLI fallback.
