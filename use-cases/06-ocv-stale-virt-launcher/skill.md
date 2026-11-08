# Skill: Fail-Proof Diagnosis for Stale Virt-Launcher Pod After Completed Migration (`06-ocv-stale-virt-launcher`)

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
| **Trigger Signal** | MCC log reports drain timeout on a pod named `(?i)virt-launcher-.*` OR Kubelet logs report: `(?i)(waiting for pod.*virt-launcher.*to terminate|error draining node.*virt-launcher)` | Exit: `not_supported: no_virt_launcher_drain_error_logged` |

---

## 2. Step-by-Step Diagnostic Procedure (Deterministic Decision Tree)

```
                            [Start: Unified Splunk Dossier Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [Step 1: Extract Virt-Launcher Target]      [No Virt-Launcher Error]
            Pod name, namespace, VM name from labels    ──► Exit: not_supported
                         │
                         ▼
            [Step 2: Dual-Launcher & Migration Verification]
            Scan KV Store for sibling pods with label vm.kubevirt.io/name
                         │
         ┌───────────────┴───────────────────────────────┐
         ▼                                               ▼
  [0 Replacement Pods on Target Node]           [Healthy Replacement Pod Found]
  Live migration DID NOT succeed!               Active VM is running on target node!
  ──► Handoff to 05-ocv-vm-not-migratable       Proceed to Step 3 (Causal Analysis)
      (DO NOT DELETE POD!)                               │
                         ┌───────────────────────────────┴───────────────────────────────┐
                         ▼                                                               ▼
            [Old Pod Stale / virt-handler Hang]                             [Dual Active Process Detected]
            Migration Succeeded metric == 1;                                Both pods consuming CPU/memory;
            old pod orphaned on source node.                                potential split-brain!
            ──► Branch 3A: Orphaned Launcher                                ──► Branch 3B: Safety Halt
```

### Step 1: Extract Blocker Pod & Identify Virtual Machine
1. Extract `target_namespace`, `failing_pod_name`, and `draining_node` from the MCC log line:
   ```regex
   (?i)error when waiting for pod "(?<target_namespace>[^/]+)/(?<failing_pod_name>virt-launcher-[^"]+)" to terminate
   ```
2. Verify in `k8s_objects` / KV Store that `target_resource == failing_pod_name`:
   * Confirm Pod label `kubevirt.io == "virt-launcher"`.
   * Extract VM name from Pod label `vm.kubevirt.io/name`.

### Step 2: Verify Active VM Status & Dual Pod State
1. Query `k8s_objects` / KV Store for all Pods in `target_namespace` matching `metadata.labels['vm.kubevirt.io/name'] == vm_name`:
   * **Case 2A: Exactly 1 pod found (the one on the draining node):**
     * The VM has NOT migrated to another node. The live migration either failed, stalled, or was never initiated.
     * **CRITICAL SAFETY ABORT:** **DO NOT DELETE THE POD.** Force-deleting this pod will crash the virtual machine and destroy customer workload state. Exit immediately to `use-cases/05-ocv-vm-not-migratable`.
   * **Case 2B: Replacement pod found on a different node (`spec.nodeName != draining_node`):**
     * Verify the replacement pod status: `status.phase == "Running"` and container condition `Ready == True`.
     * Check Prometheus metric: `kubevirt_vmi_migration_status{status="succeeded", vmi="<vm_name>"}` == 1.
     * If migration is proven succeeded and replacement launcher is healthy: Proceed to Step 3.

---

## 3. Causal Sub-Tree Analysis (The Root-Cause Engine)

```
                            [Stale Virt-Launcher on Draining Node]
                                              │
              ┌───────────────────────────────┼───────────────────────────────┐
              ▼                               ▼                               ▼
    [Branch 3A: Orphaned Pod]       [Branch 3B: Dual-Active QEMU]   [Branch 3C: Local Storage Lock]
    virt-handler failed to reap     Both pods active; split-brain   Old pod PVC lock not released
    old launcher (RH Solution 7146943) risk on shared disk           by CSI driver
              │                               │                               │
              ▼                               ▼                               ▼
    Playbook: cleanup_stale_virt_   Playbook: null (Data Risk)      Handoff: 04-storage-unmount
    launcher (Graceful pod delete)  CLI Fallback: Emergency Audit   Resolve VolumeAttachment
```

* **Branch 3A: Orphaned Source Virt-Launcher Pod (Red Hat Solution 7146943)**
  * *Evidence:* Replacement launcher pod is active and running on the target node; Prometheus `kubevirt_vmi_migration_status` is `Succeeded`; the old launcher pod on `draining_node` has `phase != "Running"` or is stuck in `Terminating` with virt-handler logs in `ocp_logs` showing `failed to delete launcher pod: context deadline exceeded`.
  * *Diagnosis:* Live migration completed 100% successfully, but virt-handler on the source node failed to reap the residual cgroup/pod container, causing MCC drainer to wait indefinitely on an orphaned pod shell.
  * *Remediation Route:* **Clean Playbook Match $\rightarrow$ `playbook_cleanup_stale_virt_launcher`**. (Safely deletes the orphaned source launcher pod, unblocking MCC drain).

* **Branch 3B: Dual-Active / Split-Brain Safety Risk**
  * *Evidence:* Both the source launcher and target launcher report active container processes or non-zero CPU metrics (`container_cpu_usage_seconds_total > 0`).
  * *Diagnosis:* Live migration entered a split-brain or incomplete handoff state where the source VM process did not suspend.
  * *Remediation Route:* **CRITICAL SAFETY HALT $\rightarrow$ Manual CLI Fallback Only.** Never delete either pod autonomously.

* **Branch 3C: Storage / PVC VolumeAttachment Lock Retained**
  * *Evidence:* Old launcher pod has finalizer `kubernetes.io/pvc-protection` or VolumeAttachment is still locked on `draining_node`.
  * *Diagnosis:* Residual storage attachment preventing launcher pod cleanup.
  * *Remediation Route:* **Handoff to `use-cases/04-storage-unmount-detach`**.

---

## 4. Remediation Resolution Rules

### Rule 1: Automated Playbook Match (`playbook_cleanup_stale_virt_launcher`)
**Conditions for Match:**
1. Branch 3A is satisfied (replacement pod is `Running` and `Ready` on target node; migration status is `Succeeded`).
2. Target node is cordoned (`spec.unschedulable == true`).
3. Source pod has been lingering for > 180s past migration completion timestamp.

**Generated Output Spec:**
```json
{
  "matched": true,
  "playbook_id": "playbook_cleanup_stale_virt_launcher",
  "playbook_file": "playbooks/remediate-stale-virt-launcher.yml",
  "risk_level": "medium",
  "requires_approval": true,
  "aap_extra_vars": {
    "target_cluster": "{{ cluster_id }}",
    "vmi_namespace": "{{ target_namespace }}",
    "vmi_name": "{{ vm_name }}",
    "stale_pod_name": "{{ failing_pod_name }}",
    "draining_node": "{{ node_name }}"
  },
  "verification_goal": "stale_pod_deleted == true and mcc_drain_resumed == true"
}
```

---

### Rule 2: Manual CLI Fallback Generation (Branch 3B - Dual-Active / Safety Risk)
**Triggered when:** Migration state is ambiguous or both pods report active processes.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Replacement pod not verified or dual-active VM process detected; requires human virtualization engineer verification.",
  "manual_cli_fallback": {
    "risk_level": "critical",
    "pre_checks": [
      "# 1. List all launcher pods for this virtual machine across all nodes:",
      "oc get pods -n {{ target_namespace }} -l vm.kubevirt.io/name={{ vm_name }} -o wide",
      "# 2. Inspect active VMI location and migration history:",
      "oc -n {{ target_namespace }} get vmi {{ vm_name }} -o jsonpath='{.status.nodeName}{\"\\n\"}'",
      "oc -n {{ target_namespace }} get vmim -l kubevirt.io/vmi-name={{ vm_name }} --sort-by=.metadata.creationTimestamp"
    ],
    "remediation_steps": [
      "# 3. Verify that the VM is indeed answering network traffic on the target node.",
      "# 4. Once target VM health is 100% verified, safely delete the stale source launcher pod:",
      "oc -n {{ target_namespace }} delete pod {{ failing_pod_name }} --grace-period=30"
    ],
    "safety_warning": "Never delete a virt-launcher pod unless the replacement pod on another node is confirmed Running and serving traffic.",
    "verification": [
      "oc get pod {{ failing_pod_name }} -n {{ target_namespace }}",
      "oc get node {{ node_name }} -o jsonpath='{.spec.unschedulable}'"
    ]
  }
}
```

---

## 5. Fail-Safe Stop Conditions & Uncertainty Downgrades

The agent MUST halt and report `inconclusive` or `not_supported` if any of the following occur:

1. **Telemetry Ingestion Failure:** Splunk multi-index query fails or returns HTTP 5xx. Report: `inconclusive: telemetry_backend_unavailable`.
2. **Missing Replacement Pod:** No replacement pod exists on another node. Report: `not_supported: vmi_migration_incomplete_route_to_05`.
3. **Ambiguous Migration Metric:** Prometheus `kubevirt_vmi_migration_status` is missing or shows `Running` (migration in-flight). Report: `inconclusive: migration_still_in_progress`.
4. **VMI Status Mismatch:** The VMI object reports `nodeName == draining_node`. Report: `not_supported: vm_still_homed_on_draining_node`.

---

## 6. Post-Remediation Verification Contract

Whether executed via AAP playbook or manual CLI, recovery MUST be proven using these exact signals:

1. **Orphan Pod Expiration:** The stale `virt-launcher` pod record is removed from `index=k8s_objects` / KV Store.
2. **Active VM Integrity:** The replacement `virt-launcher` pod on the target node remains in `phase: Running` with zero restarts.
3. **MCO Resumption:** `index=ocp_logs` records MCC progressing with node drain past the virtual machine pod.
