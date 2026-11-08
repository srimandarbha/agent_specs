# Skill: Fail-Proof Diagnosis for Node Disk Pressure or Host Resource Exhaustion (`15-disk-pressure-host-resource`)

**Version:** 2.0.0  
**Target Environment:** OpenShift 4.12+ / 4.16+ / 4.22+ / 5.0  
**Execution Context:** LangGraph Deterministic Diagnostic Node (`load_skill` -> `assess_evidence` -> `diagnose` -> `match_remediation_plan`)  
**Evidence Source:** Unified Splunk Multi-Index Search (`ocp_logs`, `k8s_objects` / KV Store, `ocp_metrics`)

---

## 1. Entry Gate & Activation Criteria (Fail-Safe Pre-Checks)

The agent MUST verify these conditions before activating this skill. If any check fails, immediately exit to `persist_and_report` with the stated status.

| Check | Requirement | Exit Action on Failure |
|---|---|---|
| **Cluster Identity** | Target `cluster_id` matches an authorized cluster in the registry. | Exit: `inconclusive: invalid_cluster_context` |
| **Lifecycle Stage** | Node drain, MCD config apply, or node update rollout is in progress or stalled. | Exit: `inconclusive: lifecycle_stage_not_node_maintenance` |
| **Trigger Signal** | Node object in `index=k8s_objects` reports condition `DiskPressure: True` or `PIDPressure: True`<br>**OR** Kubelet/MCD/MCC logs in `index=ocp_logs` match:<br>`(?i)(no space left on device|FreeDiskSpaceFailed|ImageGCFailed|failed to garbage collect images|eviction manager: node had condition: \[DiskPressure\]|maximum number of pids reached|write /etc/.*: no space left on device)`. | Exit: `not_supported: no_node_resource_pressure_detected` |

---

## 2. Step-by-Step Diagnostic Procedure (Deterministic Decision Tree)

```
                            [Start: Unified Splunk Dossier Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [Step 1: Extract Node Status & Log Errors]  [No Disk/PID Pressure Events]
            Query Node conditions & Kubelet/MCD logs    ──► Exit: not_supported
                         │
                         ▼
            [Step 2: Filesystem & Pressure Target Isolation]
            Differentiate Root (/), Container (/var/lib/containers), or PID Table
                         │
         ┌───────────────┼───────────────────────────────┬───────────────────────────────┐
         ▼               ▼                               ▼                               ▼
  [Image GC / Storage]   [Systemd Journal / Logs]        [Ephemeral Storage / emptyDir]  [PID Pressure]
  /var/lib/containers    /var/log/journal or audit.log   Pod writing unconstrained files PID table > pids.max
  ImageGCFailed in logs  filling root or /var            in container writable layer     allocatable PIDs exhausted
         │                       │                               │                               │
         ▼                       ▼                               ▼                               ▼
  Branch 3A: CRI-O Image Branch 3B: Host Journal         Branch 3C: Ephemeral Storage    Branch 3D: PID
  Storage Exhaustion     Log Exhaustion                  Quota Exhaustion                Exhaustion
```

### Step 1: Extract Node Status & Log Rejection
1. In `k8s_objects` / KV Store, inspect the target `Node` object:
   * Evaluate `status.conditions`: Find `DiskPressure` and `PIDPressure`. Record `status` (`True`/`False`), `reason`, and `message`.
   * Record `status.allocatable` and `status.capacity` for `ephemeral-storage`.
2. In `index=ocp_logs`, search for node-level storage write errors on `node_name`:
   ```regex
   (?i)(?<error_msg>no space left on device|ImageGCFailed|FreeDiskSpaceFailed|eviction manager: node had condition: \[(DiskPressure|PIDPressure)\]|maximum number of pids reached)
   ```

### Step 2: Filesystem & Pressure Target Isolation
1. **Case 2A: CRI-O Image Store / Container Storage Exhaustion:**
   * Node condition `DiskPressure: True`, and Kubelet logs report `ImageGCFailed` or `failed to garbage collect images`.
   * Metrics show `/var/lib/containers` (or container storage mount) disk usage > 85%. Proceed to **Branch 3A**.
2. **Case 2B: Host Systemd Journal or Audit Log Exhaustion:**
   * Node condition `DiskPressure: True`, and MCD logs report `write /etc/...: no space left on device` or `/var/log` usage > 95%. Proceed to **Branch 3B**.
3. **Case 2C: Pod Ephemeral Storage / emptyDir Bloat:**
   * Eviction events citing `Pod ephemeral local storage usage exceeds the total limit of containers`. Proceed to **Branch 3C**.
4. **Case 2D: PID / Process Table Saturation:**
   * Node condition `PIDPressure: True`, or Kubelet log reports `maximum number of pids reached`. Proceed to **Branch 3D**.

---

## 3. Causal Sub-Tree Analysis (The Root-Cause Engine)

```
                            [Node Resource Pressure Exhaustion]
                                             │
      ┌──────────────────────┬───────────────┴───────────────┬──────────────────────┐
      ▼                      ▼                               ▼                      ▼
[Branch 3A: Image Store] [Branch 3B: Host Journal] [Branch 3C: Ephemeral Storage] [Branch 3D: PID Pressure]
CRI-O unpruned images   Runaway systemd journal    Pod emptyDir volume bloat     Fork bomb or zombie
exhaust container pool  fills /var/log/journal     exceeds node local storage    threads hit pids.max
      │                      │                               │                      │
      ▼                      ▼                               ▼                      ▼
Playbook: null (DataRisk) Playbook: null (AuditRisk) Playbook: null (Workload)    Playbook: null (KernelRisk)
CLI: crictl rmi prune   CLI: journalctl vacuum     CLI: Evict runaway pod        CLI: Trace PID leak
```

* **Branch 3A: Container Storage & Unpruned Image Exhaustion**
  * *Evidence:* `node_filesystem_avail_bytes{mountpoint="/var/lib/containers"}` < 10%. Kubelet log contains `ImageGCFailed: failed to garbage collect images: freeDiskSpace: failed to get disk info`.
  * *Diagnosis:* CRI-O layer store is clogged with orphaned, untagged, or dangling image layers, or high-velocity CI/CD pod churn has outpaced Kubelet's background garbage collection cycle.
  * *Remediation Route:* **Manual CLI Fallback (CRI-O Image Prune & GC Tuning)**.

* **Branch 3B: Host Systemd Journal or Audit Log Exhaustion**
  * *Evidence:* `node_filesystem_avail_bytes{mountpoint="/"}` < 5% or `mountpoint="/var" < 5%`. MCD log reports `write /etc/...: no space left on device`. Host `/var/log/journal` consumes tens of gigabytes due to runaway service log loops.
  * *Diagnosis:* Un-vacuumed systemd journal or unbounded container log files on the host filesystem prevent MCD from writing rendered MachineConfig configurations or ignition forcefiles.
  * *Remediation Route:* **Manual CLI Fallback (Systemd Journal Vacuuming)**.

* **Branch 3C: Pod Ephemeral Storage / emptyDir Bloat**
  * *Evidence:* Eviction events report `The node was low on resource: ephemeral-storage`. A workload pod without `limits.ephemeral-storage` has written massive scratch files to an `emptyDir` volume located on `/var/lib/kubelet`.
  * *Diagnosis:* Rogue container wrote unconstrained data to local ephemeral disk, triggering Kubelet eviction manager threshold and tainting the node with `DiskPressure`.
  * *Remediation Route:* **Manual CLI Fallback (Identify and Evict Runaway Workload)**.

* **Branch 3D: Host PID Table Exhaustion (`PIDPressure`)**
  * *Evidence:* Node condition `PIDPressure: True`. Kubelet logs report `maximum number of pids reached`. Metrics show `node_pids{node="<node>"} >= node_pids_max`.
  * *Diagnosis:* A container has spawned hundreds of thousands of zombie processes or unmanaged threads (e.g., misconfigured Java JVM, thread leak, or fork bomb), exhausting the host PID namespace and blocking CRI-O from spawning eviction helpers or MCD hooks.
  * *Remediation Route:* **Manual CLI Fallback (Audit Process Tree & Kill Rogue Container CGroup)**.

---

## 4. Remediation Resolution Rules

### Absolute Safety Rule on Host Disk Cleanup
> [!CAUTION]
> The diagnostic agent MUST NEVER execute autonomous playbooks to delete host files or run recursive `rm -rf` inside `/var/lib/containers`, `/var/lib/kubelet`, or `/var/log`. Arbitrary file deletion under container storage destroys overlay2 layer tracking, corrupts the local BoltDB database, and leaves CRI-O permanently inoperable, forcing a complete node re-installation.

### Playbook Matching Policy
All branches of host resource pressure carry state corruption risks or require capacity planning.
* **Ansible Playbook Catalog Match:** `playbook_match: null`. (No automated playbook is authorized to delete host data or prune storage).
* **Targeted Manual CLI Fallback:** SREs receive precise, copy-pasteable read-only diagnostic commands and guarded, vendor-approved cleanup steps (`crictl rmi --prune`, `journalctl --vacuum-size`).

---

### Rule 1: Manual CLI Fallback Generation (Branch 3A - Container Storage / Image Pruning)
**Triggered when:** Node reports `DiskPressure: True` due to CRI-O container/image storage exhaustion.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Node DiskPressure caused by CRI-O container storage or image layer exhaustion in /var/lib/containers.",
  "manual_cli_fallback": {
    "risk_level": "medium",
    "pre_checks": [
      "# 1. Start a debug shell on the affected node:",
      "oc debug node/{{ target_node_name }} -- chroot /host",
      "# 2. Inspect filesystem utilization across mountpoints:",
      "df -h / /var /var/lib/containers /var/lib/kubelet",
      "# 3. Inspect inode utilization:",
      "df -ih / /var /var/lib/containers"
    ],
    "remediation_steps": [
      "# 4. Safely prune unused CRI-O image layers via container runtime:",
      "crictl rmi --prune",
      "# 5. Check if Kubelet image garbage collection thresholds need tuning via KubeletConfig CRD:",
      "oc get kubeletconfig -o yaml"
    ],
    "safety_warning": "DO NOT run 'rm -rf /var/lib/containers/storage/overlay/*' directly. Always use 'crictl rmi --prune' to ensure overlay metadata integrity.",
    "verification": [
      "crictl info | jq '.status.storage'",
      "oc get node {{ target_node_name }} -o jsonpath='{.status.conditions[?(@.type==\"DiskPressure\")].status}'"
    ]
  }
}
```

---

### Rule 2: Manual CLI Fallback Generation (Branch 3B - Host Systemd Journal Vacuuming)
**Triggered when:** Node reports `DiskPressure: True` due to journal/audit log saturation on `/` or `/var`.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Host disk space exhausted by accumulated systemd journal logs or core dumps in /var/log.",
  "manual_cli_fallback": {
    "risk_level": "medium",
    "pre_checks": [
      "# 1. Debug into node host environment:",
      "oc debug node/{{ target_node_name }} -- chroot /host",
      "# 2. Inspect journal disk usage:",
      "journalctl --disk-usage",
      "# 3. Identify largest directories under /var/log:",
      "du -sh /var/log/* | sort -hr | head -n 10"
    ],
    "remediation_steps": [
      "# 4. Safely vacuum systemd journal logs older than 2 days or exceeding 1GB:",
      "journalctl --vacuum-size=1G",
      "journalctl --vacuum-time=2d",
      "# 5. If MCD was stalled writing config, inspect MCD logs to confirm write access restored:",
      "exit",
      "oc -n openshift-machine-config-operator logs $(oc -n openshift-machine-config-operator get pods -l k8s-app=machine-config-daemon --field-selector spec.nodeName={{ target_node_name }} -o jsonpath='{.items[0].metadata.name}') -c machine-config-daemon --tail=50"
    ],
    "safety_warning": "Do not delete active systemd socket or journal directory locks while systemd-journald is running.",
    "verification": [
      "journalctl --disk-usage",
      "oc get node {{ target_node_name }} -o jsonpath='{.status.conditions[?(@.type==\"DiskPressure\")].status}'"
    ]
  }
}
```

---

### Rule 3: Manual CLI Fallback Generation (Branch 3D - Host PID Table Exhaustion)
**Triggered when:** Node reports `PIDPressure: True` due to process exhaustion.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Node PIDPressure: Host process table exhausted, blocking CRI-O from spawning processes.",
  "manual_cli_fallback": {
    "risk_level": "high",
    "pre_checks": [
      "# 1. Debug into node host environment:",
      "oc debug node/{{ target_node_name }} -- chroot /host",
      "# 2. Inspect current PID count vs kernel ceiling:",
      "sysctl kernel.pid_max",
      "ps -eLf | wc -l",
      "# 3. Identify top process trees and containers consuming PIDs:",
      "ps -eo pids,user,args --sort=-pids | head -n 20"
    ],
    "remediation_steps": [
      "# 4. Locate the rogue container or systemd cgroup leaking PIDs:",
      "systemd-cgls",
      "# 5. Stop the misbehaving container using crictl:",
      "crictl ps",
      "crictl stop {{ rogue_container_id }}"
    ],
    "safety_warning": "Killing PID 1 or core OpenShift services (crio, kubelet) will cause an unmanaged node reboot.",
    "verification": [
      "ps -eLf | wc -l",
      "oc get node {{ target_node_name }} -o jsonpath='{.status.conditions[?(@.type==\"PIDPressure\")].status}'"
    ]
  }
}
```

---

## 5. Fail-Safe Stop Conditions & Uncertainty Downgrades

The agent MUST halt and report `inconclusive` or `not_supported` if any of the following occur:

1. **Telemetry Ingestion Failure:** Splunk multi-index query fails or returns HTTP 5xx. Report: `inconclusive: telemetry_backend_unavailable`.
2. **Pressure Cleared Dynamically:** Node condition `DiskPressure: False` and `PIDPressure: False` at the moment of evaluation. Report: `not_supported: node_pressure_cleared`.
3. **Hardware Storage Controller / Read-Only Filesystem Fault:** Logs indicate `Read-only file system` or SCSI/I/O hardware bus errors. Report: `inconclusive: hardware_storage_controller_fault_requires_node_reprovisioning`.

---

## 6. Post-Remediation Verification Contract

Whether resolved via image pruning, journal vacuuming, or container eviction, recovery MUST be proven using these exact signals:

1. **Node Condition Recovery:** `DiskPressure: False` and `PIDPressure: False` on the affected node.
2. **Node Readiness:** Target node condition `Ready: True`.
3. **MCD Daemon Recovery:** MCD pod on the node successfully writes configurations without disk errors, applies the target MachineConfig, and transitions to `Done`.
4. **Pool Update Resumes:** MachineConfigPool condition `Degraded: False` and `Updating` progresses to next node.
