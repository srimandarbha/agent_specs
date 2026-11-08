---
skill_id: 03-pod-termination-finalizer
skill_version: 2.0.0
title: Fail-Proof Diagnosis for Pod Termination or Finalizer Stalls
lifecycle_stages:
- drain
- mcp_update
trigger_signatures:
- pattern: (?i)(error when waiting for pod.*to terminate|waiting for pod.*to terminate|failed
    to drain node.*pod.*terminating)
  source: ocp_logs
- pattern: 'not_supported: no_pod_termination_error_logged'
  source: ocp_logs
- pattern: '


    ### Step 1: Blocker Pod & Error Extraction

    1. Extract '
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
  - Event
  - Deployment
  - ReplicaSet
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
  negative: tests/fixtures/03-pod-termination-finalizer/negative_dossier.json
owner: platform-sre
status: draft
---

# Skill: Fail-Proof Diagnosis for Pod Termination or Finalizer Stalls (`03-pod-termination-finalizer`)

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
| **Lifecycle Stage** | Node status is `SchedulingDisabled` (cordoned), and MCO state is `Updating` (draining). | Exit: `inconclusive: lifecycle_stage_not_drain` |
| **Trigger Signal** | MCC or Kubelet log matches: `(?i)(error when waiting for pod.*to terminate|waiting for pod.*to terminate|failed to drain node.*pod.*terminating)` | Exit: `not_supported: no_pod_termination_error_logged` |

---

## 2. Step-by-Step Diagnostic Procedure (Deterministic Decision Tree)

```
                            [Start: Unified Splunk Dossier Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [Step 1: Extract Blocker Pod]              [No Termination Error]
            Namespace, Pod Name, DeletionTimestamp     ──► Exit: not_supported
                         │
                         ▼
            [Step 2: Inspect Pod Metadata & Node]
            Check deletionTimestamp, Node Ready, & metadata.finalizers
                         │
         ┌───────────────┼───────────────────────────────┐
         ▼               ▼                               ▼
  [Pod Missing/Gone]  [Node NotReady]            [Pod Has DeletionTimestamp]
  ──► Terminated!     ──► Handoff to             Evaluate metadata.finalizers
      Drain resuming      08-node-unreachable                    │
                         ┌───────────────────────────────────────┴───────────────────────────────────────┐
                         ▼                                                                               ▼
              [finalizers IS NOT empty]                                                       [finalizers IS empty / null]
              ──► Finalizer Cleanup Stalled!                                                  ──► Container Runtime / CRI-O Stalled!
                  (Proceed to Branch 3A / 3B)                                                     (Proceed to Branch 3C)
```

### Step 1: Blocker Pod & Error Extraction
1. Extract `target_namespace`, `failing_pod_name`, and elapsed termination time from MCC logs in `ocp_logs`:
   ```regex
   (?i)error when waiting for pod "(?<target_namespace>[^/]+)/(?<failing_pod_name>[^"]+)" to terminate
   ```
2. Verify in `k8s_objects` / KV Store that `target_resource == failing_pod_name`:
   * Confirm Pod `metadata.deletionTimestamp` is set.
   * If Pod is not found in KV Store or status is no longer present, the pod has already terminated. Report `not_supported: pod_already_terminated`.
   * Check target Node readiness condition:
     * If Node condition `Ready == False` or `Unknown`, Kubelet cannot report pod deletion to the API server. Handoff to `use-cases/08-node-kubelet-crio-unreachable`.

### Step 2: Differentiate Finalizer Block vs. Container Runtime Hang
1. Inspect `metadata.finalizers` array of the target Pod in `k8s_objects` / KV Store:
   * **Case 2A: `metadata.finalizers` contains entries:**
     * If any finalizer contains `pvc-protection` or `volume`: proceed to **Branch 3B (Storage Interlock)**.
     * If finalizers are custom operator or system controllers (e.g. `*.openshift.io/*`, `*.k8s.io/*`, or third-party controllers): proceed to **Branch 3A (Stalled Operator Controller)**.
   * **Case 2B: `metadata.finalizers` is empty `[]` or null:**
     * The API server is waiting for Kubelet/CRI-O to confirm all containers have stopped and cgroups have been torn down. Proceed to **Branch 3C (Container Runtime / PreStop Hang)**.

---

## 3. Causal Sub-Tree Analysis (The Root-Cause Engine)

```
                                [Pod Termination Stalled]
                                            │
              ┌─────────────────────────────┼─────────────────────────────┐
              ▼                             ▼                             ▼
    [Branch 3A: Operator Finalizer] [Branch 3B: Storage Finalizer] [Branch 3C: Hung CRI-O / PreStop]
    Custom controller dead/crashing PVC protection / Volume lock   FailedKillPod / D-state process
              │                             │                             │
              ▼                             ▼                             ▼
    Playbook: null (Data Risk)      Handoff: 04-storage-unmount   Playbook: null (Host Kernel Risk)
    CLI Fallback: Fix Controller    Resolve VolumeAttachment      CLI Fallback: Inspect CRI-O/PID
```

* **Branch 3A: Stalled Operator / Controller Finalizer**
  * *Evidence:* `metadata.finalizers` contains non-empty strings (e.g. `finalizers.kubevirt.io/...`, `operator.ibm.com/lock`, `acm.cleaner.io`).
  * *Corroboration:* Splunk query on `ocp_logs` for the owning operator shows `CrashLoopBackOff`, leader election loss, or repeated reconciliation errors (e.g., `failed to clean up external resource: connection refused`).
  * *Diagnosis:* The controlling operator responsible for executing cleanup logic before stripping its finalizer is either crashed, degraded, or unable to communicate with an external API.
  * *Remediation Route:* **DO NOT forcefully remove the finalizer autonomously.** Removing finalizers manually risks orphaning external infrastructure or state corruption. Route to **Manual CLI Fallback** with controller diagnostics.

* **Branch 3B: Storage Interlock / PVC Protection Finalizer**
  * *Evidence:* `metadata.finalizers` contains `kubernetes.io/pvc-protection` AND volume attachment for the pod's persistent volume is still locked or unmounting.
  * *Diagnosis:* The pod cannot terminate because storage unmounting is blocked by the CSI subsystem.
  * *Remediation Route:* **Handoff to `use-cases/04-storage-unmount-detach`**. Resolving the VolumeAttachment/CSI daemon issue will clear this finalizer automatically.

* **Branch 3C: Hung Container Teardown / PreStop Hook / CRI-O Deadlock**
  * *Evidence:*
    1. `metadata.finalizers` is empty or null.
    2. Elapsed time since `metadata.deletionTimestamp` exceeds `spec.terminationGracePeriodSeconds` (default 30s) by > 120s.
    3. `Event` in `k8s_objects` shows `Reason == "FailedKillPod"` with message `error killing pod: context deadline exceeded` OR `failed to "KillPodSandbox"`.
    4. Kubelet / CRI-O logs in `ocp_logs` show `uninterruptible sleep` or `preStop hook failed / deadline exceeded`.
  * *Diagnosis:* The application process is deadlocked in kernel uninterruptible sleep (`D-state`, frequently due to NFS/remote I/O hangs) or a `preStop` script is hanging indefinitely without respecting SIGTERM/SIGKILL.
  * *Remediation Route:* **Manual CLI Fallback**. Host-level inspection of the container cgroup and safe termination.

---

## 4. Remediation Resolution Rules

### Absolute Safety Rule on Finalizers
> [!CAUTION]
> The diagnostic agent MUST NEVER execute or recommend automated playbook removal of Kubernetes finalizers (`oc patch pod ... -p '{"metadata":{"finalizers":null}}'`) without explicit operator health verification and human sign-off. Stripping finalizers unconditionally can cause severe split-brain storage access and orphaned cloud infrastructure.

### Rule 1: Handoff to Storage Playbook (Branch 3B)
If Branch 3B is met and VolumeAttachment RPC failure is isolated, delegate execution to `playbook_restart_csi_driver` defined in `use-cases/04-storage-unmount-detach`.

---

### Rule 2: Manual CLI Fallback Generation (Branch 3A - Operator Finalizer Stalled)
**Triggered when:** Pod finalizer is retained by an operator or custom controller.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Finalizer retained by controller; automated deletion prohibited to prevent resource leaks.",
  "manual_cli_fallback": {
    "risk_level": "medium",
    "pre_checks": [
      "# 1. Identify lingering finalizers on the terminating pod:",
      "oc get pod {{ failing_pod_name }} -n {{ target_namespace }} -o jsonpath='{.metadata.finalizers}{\"\\n\"}'",
      "# 2. Locate the controlling operator pod in the management namespace:",
      "oc get pods -A | grep -Ei '{{ controller_keyword }}'"
    ],
    "remediation_steps": [
      "# 3. Check operator logs to identify why finalization is failing:",
      "oc -n {{ controller_namespace }} logs deployment/{{ controller_deployment }} --tail=100",
      "# 4. If the controller is in CrashLoopBackOff, restart it to allow cleanup completion:",
      "oc -n {{ controller_namespace }} rollout restart deployment/{{ controller_deployment }}",
      "# 5. CONDITIONAL ONLY: If external resources are verified clean by owner, remove finalizer manually:",
      "oc -n {{ target_namespace }} patch pod {{ failing_pod_name }} --type=merge -p '{\"metadata\":{\"finalizers\":[]}}'"
    ],
    "safety_warning": "Only patch finalizers to empty if the underlying external resource (database, cloud LB, or volume) has been manually confirmed deleted.",
    "verification": [
      "oc get pod {{ failing_pod_name }} -n {{ target_namespace }}",
      "oc get node {{ node_name }} -o jsonpath='{.spec.unschedulable}'"
    ]
  }
}
```

---

### Rule 3: Manual CLI Fallback Generation (Branch 3C - Hung PreStop / CRI-O Kill Failure)
**Triggered when:** `metadata.finalizers` is empty but pod containers fail to exit after grace period.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Container runtime failed to kill pod sandbox; potential kernel D-state process or hung preStop hook.",
  "manual_cli_fallback": {
    "risk_level": "high",
    "pre_checks": [
      "# 1. Confirm pod termination grace period expiration:",
      "oc get pod {{ failing_pod_name }} -n {{ target_namespace }} -o jsonpath='Deletion: {.metadata.deletionTimestamp}, GracePeriod: {.spec.terminationGracePeriodSeconds}{\"\\n\"}'",
      "# 2. Inspect node Kubelet / CRI-O logs for FailedKillPod events:",
      "oc adm node-logs {{ node_name }} --path=journal | grep -Ei 'FailedKillPod|KillPodSandbox|{{ failing_pod_name }}' | tail -n 30"
    ],
    "remediation_steps": [
      "# 3. Open debug session on the draining node to inspect container processes:",
      "oc debug node/{{ node_name }} -- chroot /host crictl ps --name {{ failing_pod_name }}",
      "# 4. Check for D-state processes or force kill the container sandbox via crictl:",
      "oc debug node/{{ node_name }} -- chroot /host crictl stopp <container_id>",
      "# 5. If CRI-O is unresponsive, restart crio daemon on the node:",
      "oc debug node/{{ node_name }} -- chroot /host systemctl restart crio"
    ],
    "safety_warning": "Restarting CRI-O on a draining node will stop remaining pods on that node. Ensure the node is cordoned (SchedulingDisabled) before restarting.",
    "verification": [
      "oc get pod {{ failing_pod_name }} -n {{ target_namespace }}",
      "oc adm node-logs {{ node_name }} --path=journal | grep -Ei 'kubelet.*NodeHasNoDiskPressure'"
    ]
  }
}
```

---

## 5. Fail-Safe Stop Conditions & Uncertainty Downgrades

The agent MUST halt and report `inconclusive` or `not_supported` if any of the following occur:

1. **Telemetry Ingestion Failure:** Splunk multi-index query fails or times out after 1 retry. Report: `inconclusive: telemetry_backend_unavailable`.
2. **Pod Disappeared (Race Condition):** The MCC log reports termination error, but Pod record is completely absent in both `k8s_objects` and live inventory. Report: `not_supported: pod_already_terminated`.
3. **Node Network Partition:** Target node Kubelet heartbeat is missing (`Ready: Unknown`). Inability to terminate pods is a symptom of node failure, not pod finalizer. Report: `inconclusive: node_network_partitioned_handoff_to_08`.
4. **Ambiguous Multi-Finalizer Contradiction:** Pod has multiple finalizers owned by different teams. Report: `inconclusive: multi_owner_finalizers_detected`.

---

## 6. Post-Remediation Verification Contract

Whether executed via operator recovery or human CLI steps, recovery MUST be proven using these exact signals:

1. **Pod Record Evaporation:** Target pod no longer exists in `index=k8s_objects` / KV Store lookup for the target cluster and namespace.
2. **Kubelet Clean Slate:** No new `FailedKillPod` events emitted for the affected pod UID in `index=k8s_objects` (Events).
3. **MCO Drain Resumes:** `index=ocp_logs` records MCC advancing node drain (e.g. `evicting next pod` or `drain complete for node`).
## Shared remediation catalog clarification (2026-11-08)

The `playbook_restart_csi_driver` handoff is permitted only when current evidence confirms the CSI node-driver daemon/RPC failure branch (CSI RPC timeout or equivalent driver failure) and the workload is safe for that operation. Generic custom finalizers, `pvc-protection` without a proven CSI driver fault, host process hangs and ambiguous volume state must remain manual/inconclusive. Never remove finalizers through this playbook. The shared catalog now maps UC03 to this playbook only for that narrow branch.
