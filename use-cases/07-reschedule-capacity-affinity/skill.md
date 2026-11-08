# Skill: Fail-Proof Diagnosis for Replacement Workloads Cannot Schedule After Eviction (`07-reschedule-capacity-affinity`)

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
| **Lifecycle Stage** | Node drain is in progress or completed, and workload rollout is blocked by unready replacements. | Exit: `inconclusive: lifecycle_stage_not_drain` |
| **Trigger Signal** | Replacement pods belonging to evicted workloads are stuck in `phase: Pending` AND `FailedScheduling` events in `index=k8s_objects` match: `(?i)(0/\d+ nodes available|insufficient cpu|insufficient memory|pod anti-affinity rules unsatisfied|node\(s\) had untolerated taint|volume node affinity conflict)`. | Exit: `not_supported: no_failed_scheduling_events_logged` |

---

## 2. Step-by-Step Diagnostic Procedure (Deterministic Decision Tree)

```
                            [Start: Unified Splunk Dossier Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [Step 1: Extract Pending Pod & Scheduler Reason] [No FailedScheduling Events]
            Namespace, Pod Name, Scheduler denial message   ──► Exit: not_supported
                         │
                         ▼
            [Step 2: Causal Constraint Isolation]
            Parse scheduler event reason from index=k8s_objects
                         │
         ┌───────────────┼───────────────────────────────┐
         ▼               ▼                               ▼
  [Insufficient CPU/RAM] [Anti-Affinity Unsatisfied]     [Taint / Zone Affinity]
  All schedulable nodes  Hard required anti-affinity     Untolerated taints on nodes
  lack allocatable head  rule blocks remaining nodes     or single-AZ EBS volume lock
         │                       │                               │
         ▼                       ▼                               ▼
  Branch 3A: Capacity    Branch 3B: Hard Anti-Affinity   Branch 3C: Taint / Topology
  Starvation             Deadlock                        Mismatch
```

### Step 1: Extract Pending Pod & Scheduler Rejection
1. In `k8s_objects` / KV Store, query for Pods in `target_namespace` with `status.phase == "Pending"`:
   * Record `spec.containers[*].resources.requests` (CPU and Memory).
   * Record `spec.affinity.podAntiAffinity`.
   * Record `spec.nodeSelector` and `spec.tolerations`.
2. Extract the exact scheduler rejection from `Event` objects (`reason == "FailedScheduling"`):
   ```regex
   (?i)0/(?<total_nodes>\d+) nodes available: (?<denial_details>.*)
   ```

### Step 2: Causal Constraint Isolation
1. **Case 2A: Insufficient Compute Resources (CPU / Memory):**
   * If `denial_details` contains `Insufficient cpu` or `Insufficient memory`: Proceed to **Branch 3A**.
2. **Case 2B: Pod Anti-Affinity or Topology Spread Conflict:**
   * If `denial_details` contains `pod anti-affinity rules unsatisfied` or `maxskew exceeded`: Proceed to **Branch 3B**.
3. **Case 2C: Taint / Toleration or Storage Volume Topology Mismatch:**
   * If `denial_details` contains `untolerated taint` or `volume node affinity conflict`: Proceed to **Branch 3C**.

---

## 3. Causal Sub-Tree Analysis (The Root-Cause Engine)

```
                              [Replacement Scheduling Block]
                                             │
              ┌──────────────────────────────┼──────────────────────────────┐
              ▼                              ▼                              ▼
    [Branch 3A: Capacity Starvation] [Branch 3B: Anti-Affinity]     [Branch 3C: Taint/Storage Topology]
    Allocatable CPU/RAM exhausted    Hard anti-affinity leaves no   Untolerated master/infra taint
    across all schedulable nodes     eligible nodes for replica     or single-zone PVC attachment
              │                              │                              │
              ▼                              ▼                              ▼
    Playbook: null (Capacity)        Playbook: null (Policy Risk)   Playbook: null (Architecture)
    CLI Fallback: Scale MachineSet   CLI Fallback: Relax Affinity   CLI Fallback: Taint/Zone Audit
```

* **Branch 3A: Cluster Compute Capacity Starvation**
  * *Evidence:* Scheduler event reports: `0/N nodes available: 1 node(s) were unschedulable, N-1 Insufficient cpu/memory`. Prometheus metrics show cluster-wide node allocatable memory/CPU utilized > 90%.
  * *Diagnosis:* The cluster has insufficient buffer capacity to absorb the workloads of the cordoned node.
  * *Remediation Route:* **DO NOT force-evict further pods.** Route to **Manual CLI Fallback (Scale MachineSet / Add Capacity)**.

* **Branch 3B: Hard Pod Anti-Affinity Deadlock**
  * *Evidence:* Workload specifies `requiredDuringSchedulingIgnoredDuringExecution` for its own label selector. Scheduler reports: `0/N nodes available: N-1 node(s) had pod anti-affinity rules unsatisfied`.
  * *Diagnosis:* The workload has $N$ replicas across $N$ nodes. Cordoning 1 node leaves only $N-1$ candidate nodes, making it mathematically impossible to schedule $N$ anti-affine replicas.
  * *Remediation Route:* **Manual CLI Fallback (Workload Anti-Affinity Adjustment)**. Workload owner sign-off required to convert hard anti-affinity to soft (`preferredDuringSchedulingIgnoredDuringExecution`).

* **Branch 3C: Taint / Toleration or Storage Availability Zone Pinning**
  * *Evidence:* Scheduler reports: `N node(s) had untolerated taint` OR `N node(s) had volume node affinity conflict` (PVC is bound to an EBS/SAN volume in `zone-a`, but all schedulable nodes in `zone-a` are cordoned or full). *(Note: If scheduler denial specifically cites `node(s) exceed max volume count` or `AttachableVolumesLimitExceeded`, immediately route diagnosis to `16-csi-max-volume-limit-exceeded`)*.
  * *Diagnosis:* Topology constraints prevent the pod from utilizing available capacity in other cluster zones or pools.
  * *Remediation Route:* **Manual CLI Fallback (Topology / MachineSet Rebalance)**.

---

## 4. Remediation Resolution Rules

### Absolute Safety Rule on Scheduling Policies
> [!CAUTION]
> The diagnostic agent MUST NEVER execute autonomous playbooks to mutate workload `affinity` rules, delete node taints, or alter storage topology. Hard anti-affinity rules protect databases and replicated stateful services from single-point-of-failure outages. Weakening them autonomously risks cluster-wide workload corruption.

### Rule 1: Manual CLI Fallback Generation (Branch 3A - Capacity Starvation)
**Triggered when:** Replacement pods fail scheduling due to insufficient CPU or Memory.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Cluster allocatable capacity exhausted; replacement pods cannot schedule without additional worker nodes.",
  "manual_cli_fallback": {
    "risk_level": "medium",
    "pre_checks": [
      "# 1. Inspect cluster-wide node allocatable resources vs requested:",
      "oc adm top nodes",
      "# 2. Inspect Pending pod resource requests and scheduling events:",
      "oc describe pod {{ pending_pod_name }} -n {{ target_namespace }} | grep -A 10 Events:"
    ],
    "remediation_steps": [
      "# 3. Scale up worker MachineSet to add a new worker node to the cluster:",
      "oc -n openshift-machine-api get machinesets",
      "oc -n openshift-machine-api scale machineset/{{ machineset_name }} --replicas={{ scaled_replicas }}",
      "# 4. Once new node joins and reports Ready, replacement pods will schedule automatically."
    ],
    "safety_warning": "Scaling MachineSets incurs cloud infrastructure costs. Ensure quota and budget approval.",
    "verification": [
      "oc get pod {{ pending_pod_name }} -n {{ target_namespace }} -o jsonpath='{.status.phase}'",
      "oc get nodes -o wide"
    ]
  }
}
```

---

### Rule 2: Manual CLI Fallback Generation (Branch 3B - Anti-Affinity Deadlock)
**Triggered when:** Hard anti-affinity blocks scheduling on remaining nodes.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Hard pod anti-affinity deadlock; number of replicas equals or exceeds available schedulable nodes.",
  "manual_cli_fallback": {
    "risk_level": "high",
    "pre_checks": [
      "# 1. Inspect workload pod anti-affinity rules:",
      "oc -n {{ target_namespace }} get deployment/{{ workload_name }} -o jsonpath='{.spec.template.spec.affinity.podAntiAffinity}{\"\\n\"}'"
    ],
    "remediation_steps": [
      "# 2. Workload owner sign-off required: Convert hard anti-affinity to soft (preferredDuringScheduling):",
      "# Edit deployment to replace requiredDuringScheduling with preferredDuringSchedulingIgnoredDuringExecution.",
      "# 3. Alternatively, scale deployment replicas down by 1 during node maintenance window:",
      "oc -n {{ target_namespace }} scale deployment/{{ workload_name }} --replicas={{ reduced_replicas }}"
    ],
    "safety_warning": "Scaling down or relaxing anti-affinity temporarily reduces workload redundancy. Verify with application owner before modifying.",
    "verification": [
      "oc get pod -n {{ target_namespace }} -l {{ workload_selector }} -o wide"
    ]
  }
}
```

---

## 5. Fail-Safe Stop Conditions & Uncertainty Downgrades

The agent MUST halt and report `inconclusive` or `not_supported` if any of the following occur:

1. **Telemetry Ingestion Failure:** Splunk multi-index query fails or returns HTTP 5xx. Report: `inconclusive: telemetry_backend_unavailable`.
2. **Pod Scheduled During Investigation:** Pod was in `Pending` when alert fired, but has now transitioned to `Running`. Report: `not_supported: pod_scheduled_successfully`.
3. **No Schedulable Worker Nodes:** All worker nodes in the cluster are cordoned simultaneously. Report: `inconclusive: all_nodes_cordoned_cluster_wide_maintenance`.

---

## 6. Post-Remediation Verification Contract

Whether executed via MachineSet scale-up or anti-affinity adjustment, recovery MUST be proven using these exact signals:

1. **Pending Pod Transition:** Target replacement pod transitions from `phase: Pending` to `phase: Running` and `Ready: True`.
2. **PDB Disruption Budget Restored:** Associated PDB in the namespace reports `status.disruptionsAllowed > 0`.
3. **MCO Rollout Advances:** Subsequent nodes in the MachineConfigPool can proceed with drain without being blocked by workload PDBs.
