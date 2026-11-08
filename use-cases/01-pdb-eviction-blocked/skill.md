# Skill: Fail-Proof Diagnosis for PodDisruptionBudget Blocks Eviction (`01-pdb-eviction-blocked`)

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
| **Lifecycle Stage** | Node status is `SchedulingDisabled` / cordoned, and MCO state is `Updating`. | Exit: `inconclusive: lifecycle_stage_not_drain` |
| **Trigger Signal** | MCC log contains an eviction subresource rejection matching: `(?i)(cannot evict pod.*disruption budget|eviction.*429.*too many requests)` | Exit: `not_supported: no_pdb_eviction_denial_logged` |

---

## 2. Step-by-Step Diagnostic Procedure (Deterministic Decision Tree)

```
                            [Start: Unified Splunk Dossier Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [Step 1: Extract Blocker Pod]              [No Error Log Found]
            Namespace, Pod Name, Error String           ──► Exit: not_supported
                         │
                         ▼
            [Step 2: PDB Selector Match]
            Match Pod labels against PDB spec.selector
                         │
         ┌───────────────┴───────────────┐
         ▼                               ▼
   [0 PDBs Matched]             [PDB Found in Namespace]
   ──► Check for orphan /       Verify status.disruptionsAllowed
       deleted PDB                               │
                         ┌───────────────────────┴───────────────────────┐
                         ▼                                               ▼
            [disruptionsAllowed > 0]                        [disruptionsAllowed == 0]
            ──► CONTRADICTION! Denial                       ──► PDB Block Confirmed!
                is historical or transient.                     Isolate Root Cause (Step 3)
```

### Step 1: Blocker Pod & Error Extraction
1. Extract `target_namespace` and `failing_pod_name` from the MCC log line:
   ```regex
   Cannot evict pod "(?<target_namespace>[^/]+)/(?<failing_pod_name>[^"]+)": (?<denial_message>.*)
   ```
2. Verify in `k8s_objects` / KV Store that `target_resource == failing_pod_name`:
   * Confirm Pod `metadata.labels`.
   * Confirm Pod `ownerReferences` (Deployment, StatefulSet, or ReplicaSet).

### Step 2: Correlate PDB & Evaluate Disruption Allowance
1. Scan `k8s_objects` / KV Store for `resource_kind == "PodDisruptionBudget"` in `target_namespace`.
2. Evaluate `spec.selector.matchLabels` and `matchExpressions` against the failing Pod's `metadata.labels`:
   * **Edge Case 2A: 0 PDBs match:** The PDB was deleted after the event or selector is misconfigured. Flag `probable: pdb_deleted_or_selector_mismatch`.
   * **Edge Case 2B: Multiple PDBs match:** Kubernetes prohibits overlapping PDBs. Flag `probable: overlapping_pdb_configuration`.
   * **Normal Case: Exactly 1 PDB matches:** Proceed to status evaluation.
3. Check `status.disruptionsAllowed`:
   * **If `disruptionsAllowed > 0`:** **HALT with CONTRADICTION.** The eviction failure is historical or already cleared. Do NOT recommend scaling.
   * **If `disruptionsAllowed == 0`:** Proceed to Step 3.

---

### Step 3: Causal Sub-Tree Analysis (The "Why is disruptionsAllowed == 0?" Engine)

A PDB blocking eviction is a symptom. The agent must isolate the root cause:

```
                                  [disruptionsAllowed == 0]
                                              │
              ┌───────────────────────────────┼───────────────────────────────┐
              ▼                               ▼                               ▼
       [Branch 3A: Sibling Crash]     [Branch 3B: minAvailable Equal] [Branch 3C: Single-Replica]
       currentHealthy < desiredHealthy currentHealthy == minAvailable   spec.replicas == 1 and
       Sibling in CrashLoopBackOff     All running replicas healthy     minAvailable == 1
              │                               │                               │
              ▼                               ▼                               ▼
       Playbook: null (Fix Crash)      Playbook: pdb_scale_up          Playbook: null (Arch Conflict)
       CLI Fallback: Inspect Sibling   AAP Extra Vars: Scale +1        CLI Fallback: Owner Sign-off
```

* **Branch 3A: Crashing / Unready Sibling Replica**
  * *Evidence:* `currentHealthy < desiredHealthy` in PDB status OR `kube_pod_container_status_waiting_reason{reason=~"CrashLoopBackOff|ImagePullBackOff|ContainerCreating"} > 0`.
  * *Diagnosis:* PDB disruption is blocked because existing sibling pods are unready. Evicting the target pod would cause service outage.
  * *Remediation Route:* **DO NOT scale up** (new replicas may also crash). Route to **Manual CLI Fallback** to investigate the crashing container.

* **Branch 3B: Workload at Capacity / `minAvailable` Quota Reached**
  * *Evidence:* `currentHealthy == desiredHealthy == minAvailable` AND all existing replicas report `Ready: True`.
  * *Diagnosis:* The deployment has no buffer to absorb a temporary pod drain. Scaling by +1 replica will satisfy `minAvailable` and allow eviction.
  * *Remediation Route:* **Clean Playbook Match $\rightarrow$ `playbook_pdb_scale_up`**.

* **Branch 3C: Single-Replica Architectural Conflict**
  * *Evidence:* Workload has `replicas: 1` and PDB has `minAvailable: 1` or `maxUnavailable: 0%`.
  * *Diagnosis:* Single-replica zero-downtime architectural deadlock. The node cannot drain without either scaling to 2 replicas or taking temporary downtime.
  * *Remediation Route:* **Manual CLI Fallback with Service-Owner Sign-off**.

* **Branch 3D: Replacement Pod Capacity Starvation**
  * *Evidence:* Sibling replica exists but is stuck in `phase: Pending` AND scheduler logs show `0/N nodes available: Insufficient cpu/memory`.
  * *Diagnosis:* Replacement pod cannot schedule on remaining cluster nodes.
  * *Remediation Route:* **Manual CLI Fallback (Cluster Capacity Check)**.

---

## 4. Remediation Resolution Rules

### Rule 1: Automated Playbook Match (`playbook_pdb_scale_up`)
**Conditions for Match:**
1. Branch 3B is satisfied (all current replicas healthy; `currentHealthy == minAvailable`).
2. Workload owner is a `Deployment` or `StatefulSet`.
3. Cluster-wide allocatable memory and CPU > workload pod requests.

**Generated Output Spec:**
```json
{
  "matched": true,
  "playbook_id": "playbook_pdb_scale_up",
  "playbook_file": "playbooks/remediate-pdb-scale-up.yml",
  "risk_level": "low",
  "requires_approval": true,
  "aap_extra_vars": {
    "target_cluster": "{{ cluster_id }}",
    "target_namespace": "{{ target_namespace }}",
    "workload_kind": "{{ workload_kind }}",
    "workload_name": "{{ workload_name }}",
    "target_pdb_name": "{{ target_pdb_name }}",
    "current_replicas": 2,
    "scale_to": 3
  },
  "verification_goal": "PDB disruptionsAllowed becomes >= 1 within 120s"
}
```

---

### Rule 2: Manual CLI Fallback Generation
**Triggered when:** Branch 3A (crashing sibling), Branch 3C (single-replica), Branch 3D (capacity), or unmanaged naked pod.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Crashing sibling replica detected; scaling will not resolve root cause.",
  "manual_cli_fallback": {
    "risk_level": "medium",
    "pre_checks": [
      "oc get pods -n {{ target_namespace }} -l {{ selector_string }} -o wide",
      "oc get pdb {{ target_pdb_name }} -n {{ target_namespace }}"
    ],
    "remediation_steps": [
      "# 1. Check why the sibling replica is failing readiness probes or crashing:",
      "oc -n {{ target_namespace }} logs {{ crashing_pod_name }} --previous --tail=100",
      "# 2. If crashing due to transient config, restart or fix the deployment:",
      "oc -n {{ target_namespace }} rollout restart deployment/{{ workload_name }}"
    ],
    "safety_warning": "Do not delete the remaining healthy pod on the draining node until sibling pods are in Running/Ready state.",
    "verification": [
      "oc get pdb {{ target_pdb_name }} -n {{ target_namespace }} -o jsonpath='{.status.disruptionsAllowed}'",
      "oc get node {{ node_name }} -o jsonpath='{.spec.unschedulable}'"
    ]
  }
}
```

---

## 5. Fail-Safe Stop Conditions & Uncertainty Downgrades

The agent MUST halt and report `inconclusive` or `not_supported` if any of the following occur:

1. **Tool Failure:** The Splunk multi-index query times out or returns HTTP 5xx after 1 retry. Report: `inconclusive: telemetry_backend_unavailable`.
2. **Missing PDB Record:** MCC log explicitly reports disruption budget denial, but neither `k8s_objects` nor KV Store contains a PDB matching the pod's namespace. Report: `probable: pdb_record_missing_from_cache`.
3. **Selector Ambiguity:** Pod labels match multiple conflicting PDBs in the same namespace. Report: `inconclusive: multiple_overlapping_pdbs_detected`.
4. **Stale Observation:** PDB status timestamp is older than 2 hours and no recent watch event exists. Report: `inconclusive: pdb_state_stale`.

---

## 6. Post-Remediation Verification Contract

Whether executed via AAP or manual CLI, recovery MUST be proven using these exact signals:

1. **PDB Convergence:** `status.disruptionsAllowed >= 1` in `k8s_live_inventory_lookup` or `ocp_metrics`.
2. **Eviction Success:** `index=ocp_logs` records: `Eviction of pod <pod> succeeded` OR the pod no longer appears on the draining node (`spec.nodeName != <node>`).
3. **MCO Progress:** `index=k8s_objects` / KV Store shows `desiredDrain == lastAppliedDrain` on the node, and the MachineConfigPool updating counter advances.
