# Skill: Fail-Proof Diagnosis for MachineConfigPool Paused or Coordination Block (`10-mcp-paused-or-coordination`)

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
| **Lifecycle Stage** | MachineConfigPool is expected to update or rollout is stalled at pool level. | Exit: `inconclusive: lifecycle_stage_not_updating` |
| **Trigger Signal** | Target MCP has `spec.paused == true` OR MCC logs match: `(?i)(pool.*is paused.*skipping|pool.*paused.*not updating|maxUnavailable.*nodes.*unavailable)` OR Prometheus metric `machine_config_pool_status_paused == 1`. | Exit: `not_supported: pool_is_not_paused` |

---

## 2. Step-by-Step Diagnostic Procedure (Deterministic Decision Tree)

```
                            [Start: Unified Splunk Dossier Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [Step 1: Extract MCP Spec & Status]           [spec.paused == false]
            Pool name, spec.paused, counts, conditions    Check Concurrency / Degraded
                         │                                         │
                         ▼                                         ▼
            [Evaluate spec.paused == true]                [Step 2B: Concurrency / Limits]
            Verify Degraded Condition & Node States       unavailableCount >= maxUnavailable?
                         │                                         │
         ┌───────────────┴───────────────┐               ┌─────────┴─────────┐
         ▼                               ▼               ▼                   ▼
  [Pool Condition Degraded == True] [Pool Degraded == False] [Normal Rollout] [Pool Degraded]
  DO NOT UNPAUSE!                   Verify Node Health   Serialization   Handoff to 11/12
  ──► Branch 3C: Degraded Block     (Proceed to Step 3)  ──► Exit:       (Config drift/
                                                             not_supported render apply)
```

### Step 1: Extract MachineConfigPool Configuration & Status
1. In `k8s_objects` / KV Store, lookup the target `MachineConfigPool` object:
   * Evaluate `spec.paused` (boolean).
   * Evaluate `status.conditions[?(@.type=="Degraded")].status`.
   * Record `status.machineCount`, `status.readyMachineCount`, `status.updatedMachineCount`, and `status.unavailableMachineCount`.
   * Record `spec.maxUnavailable` (integer or percentage).

### Step 2: Differentiate Stale Pause vs. Expected Concurrency Serialization
1. **If `spec.paused == false`:**
   * Compare `status.unavailableMachineCount` against `spec.maxUnavailable`:
     * If `unavailableMachineCount >= maxUnavailable`: The pool is actively updating other nodes up to its concurrency limit. This is **normal serialization behavior**, not an incident. Exit with `not_supported: pool_rollout_in_progress_respecting_concurrency_limits`.
     * If `unavailableMachineCount < maxUnavailable` and pool is stalled: Check if the pool is Degraded. If `Degraded == True`, handoff to `use-cases/11-config-drift-mcd-degraded` or `use-cases/12-mcd-config-render-apply`.
2. **If `spec.paused == true`:**
   * Evaluate `status.conditions[?(@.type=="Degraded")]`:
     * If `status == "True"`: **DO NOT UNPAUSE.** The pool was paused due to an error, or unpausing will push a broken configuration to all nodes. Proceed to **Branch 3C**.
     * If `status == "False"`: Verify that all currently ready nodes in the pool are healthy. If all nodes are healthy and a new configuration is waiting: Proceed to **Branch 3A (Stale Maintenance Pause)**.

---

## 3. Causal Sub-Tree Analysis (The Root-Cause Engine)

```
                                [MachineConfigPool Stalled]
                                             │
              ┌──────────────────────────────┼──────────────────────────────┐
              ▼                              ▼                              ▼
    [Branch 3A: Stale Pause]       [Branch 3B: Concurrency Limit] [Branch 3C: Pool Degraded Interlock]
    spec.paused == true            unavailable >= maxUnavailable  spec.paused == true AND
    Pool healthy, ready to rollout Normal serialization           Pool is Degraded (Render/Drift)
              │                              │                              │
              ▼                              ▼                              ▼
    Playbook: unpause_mcp          Exit: not_supported            Playbook: null (Safety Interlock)
    AAP Extra Vars: pool_name      (No remediation needed)        CLI Fallback: Fix Degraded First
```

* **Branch 3A: Stale Administrative Maintenance Pause (Clean Pool)**
  * *Evidence:* `spec.paused == true`; `status.conditions[?(@.type=="Degraded")].status == "False"`; `status.conditions[?(@.type=="Updated")].status == "False"`; `readyMachineCount == machineCount`; no nodes in the pool report `NotReady`.
  * *Diagnosis:* The pool was intentionally paused by an administrator for maintenance or canary validation. The maintenance window is finished, but the unpause step was omitted, leaving the rollout stalled.
  * *Remediation Route:* **Clean Playbook Match $\rightarrow$ `playbook_unpause_mcp`** (`extra_vars: { target_cluster, target_mcp_name }`).

* **Branch 3B: Rollout Serialization / MaxUnavailable Concurrency Limit**
  * *Evidence:* `spec.paused == false`; `status.unavailableMachineCount >= spec.maxUnavailable`; MCC logs show: `pool is updating, waiting for unavailable nodes to complete`.
  * *Diagnosis:* The pool is deliberately throttling node updates to honor `maxUnavailable` (default 1). Subsequent nodes cannot begin draining until the currently updating node finishes reboot and uncordons.
  * *Remediation Route:* **No remediation required.** Report `not_supported: pool_rollout_in_progress_respecting_concurrency_limits`.

* **Branch 3C: Pool Degraded Safety Interlock**
  * *Evidence:* `spec.paused == true` AND `status.conditions[?(@.type=="Degraded")].status == "True"`. MCD logs in `ocp_logs` show configuration render failure, Ignition parse error, or host config drift.
  * *Diagnosis:* The pool is degraded. Unpausing it would propagate corrupted machine configs or systemd configs across the entire cluster, risking mass node outages.
  * *Remediation Route:* **CRITICAL SAFETY INTERLOCK $\rightarrow$ Manual CLI Fallback Only.** Strictly prohibit unpausing until root cause of degradation is resolved.

---

## 4. Remediation Resolution Rules

### Rule 1: Automated Playbook Match (`playbook_unpause_mcp`)
**Conditions for Match:**
1. Branch 3A is satisfied (`spec.paused == true`, `status.conditions.Degraded == "False"`).
2. All nodes in the pool report `Ready == True`.
3. ClusterOperator `machine-config` is `Available == True`.

**Generated Output Spec:**
```json
{
  "matched": true,
  "playbook_id": "playbook_unpause_mcp",
  "playbook_file": "playbooks/remediate-unpause-mcp.yml",
  "risk_level": "medium",
  "requires_approval": true,
  "aap_extra_vars": {
    "target_cluster": "{{ cluster_id }}",
    "target_mcp_name": "{{ target_mcp_name }}"
  },
  "verification_goal": "mcp_paused == false and mcp_updating == true"
}
```

---

### Rule 2: Manual CLI Fallback Generation (Branch 3C - Pool Degraded)
**Triggered when:** Pool is paused but conditions report `Degraded: True`.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "MachineConfigPool is Degraded; unpausing prohibited to prevent cascading node failures.",
  "manual_cli_fallback": {
    "risk_level": "high",
    "pre_checks": [
      "# 1. Inspect MCP status and degraded reason:",
      "oc describe mcp {{ target_mcp_name }}",
      "# 2. Check MachineConfig Operator status:",
      "oc get co machine-config -o yaml"
    ],
    "remediation_steps": [
      "# 3. Review MCC logs for configuration render errors:",
      "oc -n openshift-machine-config-operator logs deployment/machine-config-controller -c machine-config-controller | grep -Ei 'degraded|render|error' | tail -n 30",
      "# 4. Resolve the invalid MachineConfig or drift condition before unpausing.",
      "# 5. Once Degraded condition clears, unpause the pool safely:",
      "oc patch mcp {{ target_mcp_name }} --type=merge -p '{\"spec\":{\"paused\":false}}'"
    ],
    "safety_warning": "Never unpause a Degraded MachineConfigPool without first resolving the underlying Ignition/configuration error.",
    "verification": [
      "oc get mcp {{ target_mcp_name }} -o jsonpath='{.spec.paused}{\"\\n\"}{.status.conditions[?(@.type==\"Degraded\")].status}'"
    ]
  }
}
```

---

## 5. Fail-Safe Stop Conditions & Uncertainty Downgrades

The agent MUST halt and report `inconclusive` or `not_supported` if any of the following occur:

1. **Telemetry Ingestion Failure:** Splunk multi-index query fails or returns HTTP 5xx. Report: `inconclusive: telemetry_backend_unavailable`.
2. **Missing MCP Record:** Target pool specified in alert is not found in `index=k8s_objects` or KV Store. Report: `inconclusive: mcp_record_missing`.
3. **Active Node Degradation:** One or more nodes in the pool report `Ready == False` or `Degraded == True`. Prohibit unpausing. Report: `inconclusive: pool_contains_unready_nodes`.
4. **Master / Control Plane Pool Caution:** If target pool is `master`, enforce heightened human confirmation before executing any unpause playbook.

---

## 6. Post-Remediation Verification Contract

Whether executed via AAP playbook or manual CLI, recovery MUST be proven using these exact signals:

1. **Pause Flag Cleared:** `mcp.spec.paused == false`.
2. **Rollout Transition:** `mcp.status.conditions[?(@.type=="Updating")].status == "True"`.
3. **Node Progression:** MCC logs record the first batch of nodes in the pool initiating drain or applying configurations within approved `maxUnavailable` limits.
