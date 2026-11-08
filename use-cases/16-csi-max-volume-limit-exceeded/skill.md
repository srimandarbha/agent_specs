# Skill: Fail-Proof Diagnosis for CSI Max Volume Limit Exceeded on Node (`16-csi-max-volume-limit-exceeded`)

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
| **Lifecycle Stage** | Node drain, OCV VM live migration, or post-eviction workload rescheduling is in progress or stalled. | Exit: `inconclusive: lifecycle_stage_not_drain_or_migration` |
| **Trigger Signal** | Scheduler events in `index=k8s_objects` report `reason == "FailedScheduling"` matching:<br>`(?i)0/\d+ nodes are available: \d+ node\(s\) exceed max volume count`<br>**OR** `(?i)AttachableVolumesLimitExceeded`<br>**OR** OCV `VirtualMachineInstanceMigration` fails with volume limit rejection. | Exit: `not_supported: no_max_volume_count_events_logged` |

---

## 2. Step-by-Step Diagnostic Procedure (Deterministic Decision Tree)

```
                            [Start: Unified Splunk Dossier Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [Step 1: Extract FailedScheduling Event]    [No Exceed Max Volume Events]
            Parse scheduler denial message              ──► Exit: not_supported
                         │
                         ▼
            [Step 2: Execute Node Volume Tally Engine]
            For each candidate node in pool:
            • Max limit: CSINode spec.drivers[].allocatable.count OR Node attachable-volumes
            • Current used: Count(VolumeAttachment where spec.nodeName==node AND status.attached==true)
            • Headroom = Max limit - Current used
                         │
         ┌───────────────┼───────────────────────────────┐
         ▼               ▼                               ▼
  [Cluster-Wide Saturation] [Single CSI Driver Limit]    [Driver Misconfiguration]
  >90% nodes have 0 headroom All candidate nodes hit     CSI driver allocatable count set
  across all CSI drivers    specific driver limit (e.g. MapR, too low (e.g. 20) vs host SAN limit
         │                  AWS EBS, Trident, Portworx)          │
         ▼                       │                               ▼
  Branch 3A: Fleet Volume        ▼                       Branch 3C: CSI Driver Quota
  Capacity Exhaustion     Branch 3B: Driver-Specific     Under-Allocated
                          Attachable Saturation
```

### Step 1: Extract Blocked Workload & Scheduler Denial
1. In `k8s_objects` / KV Store, locate the `Event` with `reason == "FailedScheduling"` for the affected `Pod` or `virt-launcher` replacement pod:
   ```regex
   (?i)0/(?<total_nodes>\d+) nodes are available: (?<denied_nodes>\d+) node\(s\) exceed max volume count
   ```
2. Identify the workload's required PersistentVolumeClaims (PVCs) and their associated CSI driver names (`spec.volumes[*].persistentVolumeClaim`).

### Step 2: Execute Node Volume Tally Engine
The agent computes the attachable volume budget across all candidate worker nodes in the cluster/pool:
1. **Maximum Volume Ceiling ($V_{max}$):**
   * Inspect `CSINode` objects: `spec.drivers[?(@.name == "<csi_driver_name>")].allocatable.count`.
   * Cross-reference `Node` objects: `status.allocatable["attachable-volumes-csi-<driver-name>"]` or driver configuration `MAX_VOLUMES_PER_NODE`.
2. **Current Attached Volumes ($V_{used}$):**
   * From `k8s_objects` / KV Store, count all active `VolumeAttachment` objects:
     $$V_{used}(N) = \left| \{ \text{VolumeAttachment} \mid \text{spec.nodeName} == N \land \text{status.attached} == \text{true} \} \right|$$
3. **Volume Headroom ($V_{headroom}$):**
   $$V_{headroom}(N) = V_{max}(N) - V_{used}(N)$$
4. If $V_{headroom}(N) \le 0$ across all schedulable candidate nodes, volume attachment limit exhaustion is mathematically proven.

---

## 3. Causal Sub-Tree Analysis (The Root-Cause Engine)

```
                            [Node Max Volume Limit Exceeded]
                                             │
      ┌──────────────────────────────────────┼──────────────────────────────────────┐
      ▼                                      ▼                                      ▼
[Branch 3A: Fleet Capacity Exhaustion] [Branch 3B: Specific CSI Driver Limit] [Branch 3C: Driver Under-Allocated]
All worker nodes at maximum volume    CSI driver (MapR/EBS/Trident) has      CSINode allocatable count is set
count (e.g. 200/200 volumes on >90%)   hard limit; nodes full for that driver to low default (e.g. 20) vs host capability
      │                                      │                                      │
      ▼                                      ▼                                      ▼
Playbook: null (Capacity expansion)   Playbook: null (Topology/Rebalance)   Playbook: null (Vendor Config Risk)
CLI: Scale Worker MachineSet          CLI: Rebalance Workload PVCs           CLI: Reconfigure CSI Driver Count
```

* **Branch 3A: Fleet-Wide Volume Capacity Exhaustion**
  * *Evidence:* $V_{used} / V_{max} \ge 90\%$ across all schedulable worker nodes in the target pool (e.g., each node holds 200/200 attached volumes).
  * *Diagnosis:* Upgrade drain or VM live migration cannot evacuate pods because the cluster has run out of volume attachment slots fleet-wide.
  * *Remediation Route:* **Manual CLI Fallback (Scale Worker MachineSet / Add Nodes)**. Adding worker nodes provides fresh CSI volume attach slots.

* **Branch 3B: Driver-Specific Attachable Volume Saturation**
  * *Evidence:* Scheduler rejection is isolated to a specific storage driver (e.g., `com.mapr.csi-kdf`, `ebs.csi.aws.com`, `netapp.trident.csi`), while generic CPU/RAM is abundant.
  * *Diagnosis:* Workloads utilizing this specific storage class are disproportionately concentrated on candidate nodes, exhausting the CSI driver's allocatable slots.
  * *Remediation Route:* **Manual CLI Fallback (Workload Rebalancing / Drain Sequencing)**.

* **Branch 3C: CSI Driver Quota Under-Allocation (`spec.drivers[].allocatable.count`)**
  * *Evidence:* `CSINode` `allocatable.count` is configured to an artificially low ceiling (e.g., 20 or 39 volumes) while host hardware and hypervisor limits permit higher counts (e.g., 64 or 200).
  * *Diagnosis:* The CSI driver's node daemon or storage operator configuration limits volume density unnecessarily.
  * *Remediation Route:* **Manual CLI Fallback (CSI Driver Configuration Re-alignment)**. Storage vendor approval required before modifying driver DaemonSet environment variables (`MAX_VOLUMES_PER_NODE`).

---

## 4. Remediation Resolution Rules

### Absolute Safety Rule on Storage Driver Reconfiguration
> [!CAUTION]
> The diagnostic agent MUST NEVER execute autonomous playbooks to patch `CSINode` objects, modify CSI driver DaemonSet configurations, or alter `MAX_VOLUMES_PER_NODE` environment variables. Storage controller reconfiguration can cause active storage drivers to restart or drop existing iSCSI/NVMe/SAN sessions, resulting in storage detachment outages across healthy nodes.

### Playbook Matching Policy
* **Ansible Playbook Catalog Match:** `playbook_match: null`. (No automated playbook exists in [`PLAYBOOK_CATALOG.json`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/remediations/PLAYBOOK_CATALOG.json) for cluster storage topology reconfiguration).
* **Targeted Manual CLI Fallback:** SREs receive precise, copy-pasteable read-only diagnostic inspection commands and guarded remediation procedures.

---

### Rule 1: Manual CLI Fallback Generation (Branch 3A - Fleet Capacity Exhaustion)
**Triggered when:** Volume tally engine confirms $>90\%$ of candidate nodes have zero volume headroom.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Cluster-wide CSI volume attachment limit exhausted; candidate nodes exceed max volume count.",
  "manual_cli_fallback": {
    "risk_level": "medium",
    "pre_checks": [
      "# 1. Inspect scheduler denial events:",
      "oc get events -n {{ target_namespace }} --field-selector reason=FailedScheduling",
      "# 2. Inspect active volume attachments across candidate nodes:",
      "oc get volumeattachment -o custom-columns=NODE:.spec.nodeName,ATTACHED:.status.attached | sort | uniq -c",
      "# 3. Inspect CSINode allocatable counts:",
      "oc get csinode {{ candidate_node }} -o yaml | grep -A 5 allocatable"
    ],
    "remediation_steps": [
      "# 4. Scale up worker MachineSet to add new worker nodes (each new node provides additional volume attach slots):",
      "oc -n openshift-machine-api get machinesets",
      "oc -n openshift-machine-api scale machineset/{{ machineset_name }} --replicas={{ scaled_replicas }}",
      "# 5. Once new node is Ready and CSINode is registered, migration/rescheduling will resume automatically."
    ],
    "safety_warning": "Adding nodes incurs cloud infrastructure costs. Ensure quota and budget approval.",
    "verification": [
      "oc get pod {{ blocked_pod_name }} -n {{ target_namespace }} -o jsonpath='{.status.phase}'",
      "oc get volumeattachment -o wide"
    ]
  }
}
```

---

### Rule 2: Manual CLI Fallback Generation (Branch 3C - CSI Driver Allocatable Tuning)
**Triggered when:** `CSINode` `spec.drivers[].allocatable.count` is artificially constrained.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "CSI driver allocatable count on candidate nodes reached vendor-configured ceiling.",
  "manual_cli_fallback": {
    "risk_level": "high",
    "pre_checks": [
      "# 1. Check current CSINode allocatable count for driver {{ csi_driver_name }}:",
      "oc get csinode -o jsonpath='{range .items[*]}{.metadata.name}{\"\\t\"}{.spec.drivers[?(@.name==\"{{ csi_driver_name }}\")].allocatable.count}{\"\\n\"}{end}'",
      "# 2. Inspect CSI driver DaemonSet configuration and environment variables:",
      "oc -n {{ csi_namespace }} get daemonset/{{ csi_daemonset }} -o yaml | grep -i MAX_VOLUMES"
    ],
    "remediation_steps": [
      "# 3. Contact storage vendor/support (Red Hat Data Foundation / Storage Vendor) before modifying MAX_VOLUMES_PER_NODE.",
      "# 4. If vendor confirms higher node attach limit is supported, update driver configuration via GitOps or operator CRD.",
      "# 5. Avoid editing CSINode directly (it is an ephemeral status object overwritten by Kubelet/CSI driver)."
    ],
    "safety_warning": "Modifying CSI driver volume limits beyond hypervisor/hardware SAN ceilings causes kernel SCSI bus lockups.",
    "verification": [
      "oc get csinode {{ candidate_node }} -o yaml",
      "oc get events -A --field-selector reason=FailedScheduling --sort-by=.lastTimestamp"
    ]
  }
}
```

---

## 5. Fail-Safe Stop Conditions & Uncertainty Downgrades

The agent MUST halt and report `inconclusive` or `not_supported` if any of the following occur:

1. **Telemetry Ingestion Failure:** Splunk multi-index query fails or returns HTTP 5xx. Report: `inconclusive: telemetry_backend_unavailable`.
2. **Pod Scheduled During Investigation:** Pod was in `Pending` when alert fired, but has now scheduled (`phase: Running`). Report: `not_supported: pod_scheduled_successfully`.
3. **No FailedScheduling Events:** No events matching `exceed max volume count` found in `index=k8s_objects`. Report: `not_supported: no_max_volume_count_events_logged`.

---

## 6. Post-Remediation Verification Contract

Whether resolved via worker MachineSet scale-out or workload rebalancing, recovery MUST be proven using these exact signals:

1. **Scheduler Clearance:** `FailedScheduling` events for target pod / `virt-launcher` cease.
2. **VolumeAttachment Created & Attached:** New `VolumeAttachment` object created on destination node with `status.attached: true`.
3. **Workload / VM Running:** Target pod transitions to `phase: Running` and `Ready: True`, or OCV `VirtualMachineInstance` reports `migrationState.completed: true`.
4. **MCO Rollout Advances:** Subsequent nodes in the MachineConfigPool proceed with drain.
