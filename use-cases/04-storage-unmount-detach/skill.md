---
skill_id: 04-storage-unmount-detach
skill_version: 2.0.0
title: Fail-Proof Diagnosis for Storage Unmount or Detach Stalls
lifecycle_stages:
- drain
- mcp_update
trigger_signatures:
- pattern: (?i)(failed to unmount|unmountdevice failed|failed to detach|volume.*still
    attached|volumeattachment.*in use|device or resource busy)
  source: ocp_logs
- pattern: 'not_supported: no_storage_unmount_error_logged'
  source: ocp_logs
- pattern: "regex\n   (?i)UnmountDevice failed for volume \"(?<volume_name>[^\"]+)\"\
    .*pod \"(?<target_namespace>[^/]+)/(?<failing_pod_name>[^\"]+)\"\n   "
  source: ocp_logs
supported_environments:
  openshift_versions:
  - 4.12+
  - 4.16+
  - 4.22+
  - '5.0'
  mco_versions:
  - 4.12+
  components:
  - name: machine-config-controller
  - name: machine-config-daemon
  - name: kubelet
  - name: kube-apiserver
  - name: openshift-virtualization
  - name: csi-driver
required_evidence:
- dataset: ocp_logs
  kinds: &id001
  - Pod
  - Node
  - PersistentVolumeClaim
  - PersistentVolume
  - VolumeAttachment
  - DaemonSet
  - Event
  max_age_seconds: 3600
- dataset: k8s_objects
  kinds: *id001
  max_age_seconds: 300
- dataset: prometheus
  metrics:
  - declared_by_skill_and_observability_matrix
  max_age_seconds: 300
freshness_limits_seconds:
  node_and_lease: 120
  pod_pdb_storage: 300
  mcp_and_operator: 600
decision_tree_version: 1.0.0
prohibited_actions:
- direct Kubernetes mutation
- force deletion
- unreviewed finalizer removal
- unapproved AAP execution
remediation_catalog_refs: []
evaluation_fixtures:
  negative: tests/fixtures/04-storage-unmount-detach/negative_dossier.json
owner: platform-sre
status: draft
---

# Skill: Fail-Proof Diagnosis for Storage Unmount or Detach Stalls (`04-storage-unmount-detach`)

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
| **Lifecycle Stage** | Node status is `SchedulingDisabled` (cordoned), and pod termination is actively stalled. | Exit: `inconclusive: lifecycle_stage_not_drain` |
| **Trigger Signal** | Kubelet or CSI logs in `ocp_logs` match: `(?i)(failed to unmount|unmountdevice failed|failed to detach|volume.*still attached|volumeattachment.*in use|device or resource busy)` | Exit: `not_supported: no_storage_unmount_error_logged` |

---

## 2. Step-by-Step Diagnostic Procedure (Deterministic Decision Tree)

```
                            [Start: Unified Splunk Dossier Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [Step 1: Extract Storage Target]           [No Storage Error Found]
            Namespace, Pod Name, Volume Name           ──► Exit: not_supported
                         │
                         ▼
            [Step 2: VolumeAttachment Lookup]
            Look up VolumeAttachment for Node + PV in KV Store
                         │
         ┌───────────────┴───────────────┐
         ▼                               ▼
   [attached == false]            [attached == true OR detachError != null]
   ──► Unmount completed!         ──► Detach Stalled!
       Storage is cleared.            Isolate Root Cause (Step 3)
```

### Step 1: Storage Target & Pod Extraction
1. Extract `target_namespace`, `failing_pod_name`, and `volume_name` from the Kubelet or MCC log error:
   ```regex
   (?i)UnmountDevice failed for volume "(?<volume_name>[^"]+)".*pod "(?<target_namespace>[^/]+)/(?<failing_pod_name>[^"]+)"
   ```
2. Verify in `k8s_objects` / KV Store that `target_resource == failing_pod_name`:
   * Confirm Pod `metadata.deletionTimestamp` is set (pod is actively terminating).
   * Confirm Pod volume reference maps to the target PVC / PV.

### Step 2: VolumeAttachment & Node Status Check
1. Scan `k8s_objects` / KV Store for `resource_kind == "VolumeAttachment"` where `node_name == draining_node` and `volume_name == target_pv`:
   * **Case 2A: `status.attached == false` AND no detachError:** The volume has detached successfully. The stall is caused by application shutdown or finalizers, NOT storage. Exit to `use-cases/03-pod-termination-finalizer`.
   * **Case 2B: `status.attached == true` OR `status.detachError != null`:** Confirmed storage unmount/detach stall. Proceed to Step 3.

---

### Step 3: Causal Sub-Tree Analysis (The Root-Cause Engine)

```
                                [Storage Detach Stalled]
                                           │
             ┌─────────────────────────────┼─────────────────────────────┐
             ▼                             ▼                             ▼
   [Branch 3A: Hung CSI Daemon]  [Branch 3B: Multi-Attach Lock] [Branch 3C: Target Busy]
   RPC timeout / CSI plugin hang  Cloud/Array lock conflict     Host process holds mount open
             │                             │                             │
             ▼                             ▼                             ▼
   Playbook: restart_csi_driver  Playbook: null (Backend Lock)  Playbook: null (Host Busy)
   AAP Extra Vars: CSI daemon    CLI Fallback: Storage Admin    CLI Fallback: fuser / lsof
```

* **Branch 3A: Hung CSI Node-Driver DaemonSet Pod on the Draining Node**
  * *Evidence:* `VolumeAttachment.status.detachError` contains `rpc error: code = DeadlineExceeded` OR CSI node pod logs in `ocp_logs` show connection timeouts while Kubelet logs show `UnmountDevice failed`.
  * *Diagnosis:* The local CSI node daemonset pod on the draining node is deadlocked or hung, failing to unmount the filesystem from the host.
  * *Remediation Route:* **Clean Playbook Match $\rightarrow$ `playbook_restart_csi_driver`**. (Restarting the daemonset pod on that specific node clears the hung RPC handler).

* **Branch 3B: Storage Backend Lock / Multi-Attach Conflict**
  * *Evidence:* `VolumeAttachment.status.detachError` contains `Multi-Attach error for volume` OR `Volume is already exclusively attached to one node`.
  * *Diagnosis:* Cloud/SAN storage control plane still holds an exclusive volume lease, or another node attempted to attach the volume before this node completed unmounting.
  * *Remediation Route:* **Manual CLI Fallback (Do NOT restart local CSI pod)**. Requires storage control plane coordination.

* **Branch 3C: Host Process Holding Mount Point Open (`device or resource busy`)**
  * *Evidence:* Kubelet journal logs show: `umount: ...: target is busy` OR `device or resource busy`.
  * *Diagnosis:* A container process, zombie process, or lingering sub-mount namespace on the host is still accessing the volume directory.
  * *Remediation Route:* **Manual CLI Fallback (Host Process Inspection)**.

---

## 4. Remediation Resolution Rules

### Rule 1: Automated Playbook Match (`playbook_restart_csi_driver`)
**Conditions for Match:**
1. Branch 3A is satisfied (RPC timeout / CSI node daemon hang).
2. CSI driver pod on the draining node is identified (e.g. `csi-rbdplugin`, `aws-ebs-csi-driver-node`, `vsphere-csi-node`).
3. Target node is already cordoned (`SchedulingDisabled`).

**Generated Output Spec:**
```json
{
  "matched": true,
  "playbook_id": "playbook_restart_csi_driver",
  "playbook_file": "playbooks/remediate-restart-csi-driver.yml",
  "risk_level": "low",
  "requires_approval": true,
  "aap_extra_vars": {
    "target_cluster": "{{ cluster_id }}",
    "draining_node": "{{ node_name }}",
    "csi_driver_namespace": "{{ csi_namespace }}",
    "csi_driver_daemonset": "{{ csi_daemonset_name }}"
  },
  "verification_goal": "VolumeAttachment status.attached becomes false within 120s"
}
```

---

### Rule 2: Manual CLI Fallback Generation
**Triggered when:** Branch 3B (multi-attach lock), Branch 3C (target busy), or non-standard third-party storage driver.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Storage backend lock or busy mount detected; requires human verification to prevent data corruption.",
  "manual_cli_fallback": {
    "risk_level": "high",
    "pre_checks": [
      "# 1. Check VolumeAttachment status and error message:",
      "oc get volumeattachment -o wide | grep {{ volume_name }}",
      "# 2. Inspect CSI driver controller logs:",
      "oc -n {{ csi_namespace }} logs deployment/{{ csi_controller }} -c csi-driver --tail=50"
    ],
    "remediation_steps": [
      "# 3. If host mount is busy, inspect open file descriptors on the draining node:",
      "oc adm node-logs {{ node_name }} --path=journal | grep -Ei 'umount.*busy|{{ volume_name }}'",
      "# 4. WARNING: Never force-delete VolumeAttachment without confirming disk is unmounted from host!"
    ],
    "safety_warning": "Force-detaching a volume while a host process is actively writing will cause silent filesystem corruption.",
    "verification": [
      "oc get volumeattachment | grep {{ volume_name }}",
      "oc get pod {{ failing_pod_name }} -n {{ target_namespace }}"
    ]
  }
}
```

---

## 5. Fail-Safe Stop Conditions & Uncertainty Downgrades

The agent MUST halt and report `inconclusive` or `not_supported` if any of the following occur:

1. **Tool Failure:** The Splunk multi-index query times out or returns HTTP 5xx. Report: `inconclusive: telemetry_backend_unavailable`.
2. **Missing VolumeAttachment:** Kubelet reports detach error, but no matching `VolumeAttachment` exists in `k8s_objects` or KV Store. Report: `probable: volume_attachment_record_missing`.
3. **Active Workload Risk:** Workload pod on draining node is still in `phase: Running` (not `Terminating`). **HALT IMMEDIATELY.** Never recommend detaching a volume for a running pod. Report: `not_supported: pod_not_in_terminating_state`.

---

## 6. Post-Remediation Verification Contract

Whether executed via AAP or manual CLI, recovery MUST be proven using these exact signals:

1. **VolumeAttachment Detached:** `status.attached == false` OR the `VolumeAttachment` object is deleted from the cluster.
2. **Pod Termination:** The blocker pod finishes termination and is removed from `spec.nodeName == draining_node`.
3. **MCO Drain Resumes:** `index=ocp_logs` records MCC progressing with node drain.
