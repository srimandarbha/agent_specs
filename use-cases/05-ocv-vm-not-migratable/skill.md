# Skill: Fail-Proof Diagnosis for OpenShift Virtualization VM Not Live-Migratable (`05-ocv-vm-not-migratable`)

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

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
| **Lifecycle Stage** | Node status is `SchedulingDisabled` (cordoned), and MCO is draining the node. | Exit: `inconclusive: lifecycle_stage_not_drain` |
| **Trigger Signal** | MCC eviction log matches: `(?i)(virt-launcher-eviction-interceptor.*not live-migratable|cannot migrate vmi|VMI is configured with an eviction strategy but is not live-migratable)` OR Prometheus metric `kubevirt_vmi_non_evictable > 0`. | Exit: `not_supported: no_vmi_migration_block_logged` |

---

## 2. Step-by-Step Diagnostic Procedure (Deterministic Decision Tree)

```
                            [Start: Unified Splunk Dossier Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [Step 1: Extract VM & Interceptor Rejection]  [No Eviction Interceptor Error]
            Pod name, namespace, VM name, denial reason  ──► Exit: not_supported
                         │
                         ▼
            [Step 2: Prometheus Metric & Reason Evaluation]
            Query kubevirt_vmi_non_evictable{vmi=vm_name}
                         │
         ┌───────────────┼───────────────────────────────┐
         ▼               ▼                               ▼
  [DisksNotMigratable]   [HostDevicesNotMigratable]      [NoDestinationNode]
  Non-shared storage /   PCI passthrough / GPU /         Target capacity, affinity,
  local RWO PVC          SR-IOV binding                  or CPU model mismatch
         │                       │                               │
         ▼                       ▼                               ▼
  Branch 3A: Storage     Branch 3B: Host Device          Branch 3C: Target Scheduling
  Constraint             Binding                         Deadlock
```

### Step 1: Extract VM & Interceptor Rejection
1. Extract `target_namespace`, `failing_pod_name`, and eviction denial message from MCC logs in `ocp_logs`:
   ```regex
   (?i)Cannot evict pod "(?<target_namespace>[^/]+)/(?<failing_pod_name>virt-launcher-[^"]+)".*virt-launcher-eviction-interceptor.*"(?<denial_reason>[^"]+)"
   ```
2. Verify in `k8s_objects` / KV Store that `target_resource == failing_pod_name`:
   * Confirm Pod label `kubevirt.io == "virt-launcher"`.
   * Extract VM name from Pod label `vm.kubevirt.io/name`.

### Step 2: Correlate Prometheus OCV Metrics
1. Inspect `index=ocp_metrics` for the target VM:
   * Query: `kubevirt_vmi_non_evictable{vmi="<vm_name>"}`:
     * Label `reason`: `DisksNotMigratable`, `HostDevicesNotMigratable`, `InternalError`.
   * Query: `kubevirt_vmi_migration_status{vmi="<vm_name>"}`:
     * Status `Failed` with reason `TargetNodeNotSchedulable`, `MigrationNetworkDegraded`, or `Cancelled`.

---

## 3. Causal Sub-Tree Analysis (The Root-Cause Engine)

```
                            [VM Live Migration Blocked]
                                         │
            ┌────────────────────────────┼────────────────────────────┐
            ▼                            ▼                            ▼
  [Branch 3A: Local Storage]   [Branch 3B: Host Devices]    [Branch 3C: No Target Node]
  Non-shared disk (RWO local   PCI/GPU/SR-IOV hardware      Affinity, CPU model, or
  PV, hostPath, or clone disk) passthrough pinned to host   capacity exhaustion on target
            │                            │                            │
            ▼                            ▼                            ▼
  Playbook: null (Data Risk)   Playbook: null (Hardware)    Playbook: null (Capacity)
  CLI Fallback: Storage Plan   CLI Fallback: Hardware Audit CLI Fallback: Capacity Check
```

* **Branch 3A: Non-Shared Storage / Local PV Disk Constraint**
  * *Evidence:* Prometheus metric `kubevirt_vmi_non_evictable{reason="DisksNotMigratable"} == 1` OR `virt-handler` logs show: `cannot migrate VMI with non-shared storage; volume is ReadWriteOnce or hostPath`.
  * *Diagnosis:* Live migration requires storage to be shared across nodes (e.g. Ceph RBD / CephFS in `ReadWriteMany` mode or SAN shared block). The VM is attached to a local disk or non-sharable volume.
  * *Remediation Route:* **DO NOT forcefully delete the pod or mutate eviction strategy autonomously.** Route to **Manual CLI Fallback** for storage owner coordination or controlled guest shutdown.

* **Branch 3B: Host Device Binding / PCI Passthrough / GPU Pinning**
  * *Evidence:* Prometheus metric `kubevirt_vmi_non_evictable{reason="HostDevicesNotMigratable"} == 1` OR `virt-handler` logs report `VMI has assigned hostDevices: pci/gpu`.
  * *Diagnosis:* The virtual machine is bound to physical hardware on the draining node (e.g. Nvidia GPU, vGPU, or specialized PCIe device) that cannot be migrated across hypervisors over the network.
  * *Remediation Route:* **Manual CLI Fallback**. Requires scheduled maintenance window to shut down the VM, allow node update, and restart.

* **Branch 3C: Destination Node Scheduling Deadlock / Capacity Starvation**
  * *Evidence:* Prometheus metric `kubevirt_vmi_migration_status{status="failed"}` with reason `NoNodesAvailable`, or virt-controller logs report `0/N nodes available: Insufficient cpu/memory` or `node affinity mismatch`. *(Note: If target node scheduling failure specifically cites `node(s) exceed max volume count`, immediately route diagnosis to `16-csi-max-volume-limit-exceeded`)*.
  * *Diagnosis:* The VM is migratable in principle, but no other node in the cluster satisfies its CPU model requirements, NUMA constraints, or memory footprint.
  * *Remediation Route:* **Manual CLI Fallback (Cluster Capacity / Node Affinity Audit)**.

---

## 4. Remediation Resolution Rules

### Absolute Safety Rule on Virtual Machines
> [!CAUTION]
> The diagnostic agent MUST NEVER execute autonomous playbooks to patch VM eviction strategies (`evictionStrategy: None`), power off virtual machines (`virtctl stop`), or force-delete `virt-launcher` pods. Doing so without application-owner sign-off will cause unrecoverable guest filesystem damage or enterprise service outages.

### Rule 1: Manual CLI Fallback Generation (Branch 3A - Non-Shared Storage)
**Triggered when:** VM is blocked by non-shared storage disks.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "VM uses non-shared storage disks; live migration is impossible without shared storage or scheduled shutdown.",
  "manual_cli_fallback": {
    "risk_level": "high",
    "pre_checks": [
      "# 1. Inspect VMI non-migratable conditions and disk attachments:",
      "oc -n {{ target_namespace }} get vmi {{ vm_name }} -o jsonpath='{.status.conditions[?(@.type==\"LiveMigratable\")].message}{\"\\n\"}'",
      "# 2. List PVCs used by this virtual machine and their access modes:",
      "oc -n {{ target_namespace }} get pvc -l vm.kubevirt.io/name={{ vm_name }}"
    ],
    "remediation_steps": [
      "# Option A (Recommended for planned upgrades): Perform controlled shutdown with workload owner:",
      "virtctl stop {{ vm_name }} -n {{ target_namespace }}",
      "# Option B (If VM is stateless): Temporarily change eviction strategy to allow node drain:",
      "# oc -n {{ target_namespace }} patch vm {{ vm_name }} --type=merge -p '{\"spec\":{\"template\":{\"spec\":{\"evictionStrategy\":\"None\"}}}}'"
    ],
    "safety_warning": "Option A stops the VM guest OS. Ensure workload owner sign-off and valid database backups exist before stopping.",
    "verification": [
      "oc get pod {{ failing_pod_name }} -n {{ target_namespace }}",
      "oc get node {{ node_name }} -o jsonpath='{.spec.unschedulable}'"
    ]
  }
}
```

---

### Rule 2: Manual CLI Fallback Generation (Branch 3B - Host Devices / GPU)
**Triggered when:** VM has PCI / GPU passthrough bindings.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "VM is hardware-bound to host GPU/PCI devices; requires controlled power-off for host maintenance.",
  "manual_cli_fallback": {
    "risk_level": "high",
    "pre_checks": [
      "# 1. Check hardware devices assigned to the VM:",
      "oc -n {{ target_namespace }} get vm {{ vm_name }} -o jsonpath='{.spec.template.spec.domain.devices.hostDevices}{\"\\n\"}'"
    ],
    "remediation_steps": [
      "# 2. Schedule maintenance window and stop the VM gracefully:",
      "virtctl stop {{ vm_name }} -n {{ target_namespace }}",
      "# 3. Once node maintenance is complete, restart the VM:",
      "virtctl start {{ vm_name }} -n {{ target_namespace }}"
    ],
    "safety_warning": "GPU workloads cannot live-migrate. Stopping the VM will terminate running GPU jobs.",
    "verification": [
      "oc get pod {{ failing_pod_name }} -n {{ target_namespace }}"
    ]
  }
}
```

---

## 5. Fail-Safe Stop Conditions & Uncertainty Downgrades

The agent MUST halt and report `inconclusive` or `not_supported` if any of the following occur:

1. **Telemetry Ingestion Failure:** Splunk multi-index query fails or returns HTTP 5xx. Report: `inconclusive: telemetry_backend_unavailable`.
2. **Missing VM Pod:** Pod named in MCC log is not found in `k8s_objects` or KV Store. Report: `inconclusive: virt_launcher_pod_missing`.
3. **VM Already Stopped:** The VM has already been shut down between drain timeout and agent execution. Report: `not_supported: vm_already_stopped`.
4. **Transient Network Error:** Live migration failed due to transient network timeout, but VMI reports `LiveMigratable: True`. Report: `probable: transient_migration_network_timeout`.

---

## 6. Post-Remediation Verification Contract

Whether executed via controlled shutdown or storage migration, recovery MUST be proven using these exact signals:

1. **Launcher Eviction Complete:** The `virt-launcher` pod on the draining node terminates and is removed from `index=k8s_objects` / KV Store.
2. **MCC Drain Resumes:** `index=ocp_logs` records MCC advancing node drain past the virtual machine.
3. **Workload Restored Post-Maintenance:** Post-maintenance logs confirm VM successfully migrated to another node or restarted upon uncordon.
