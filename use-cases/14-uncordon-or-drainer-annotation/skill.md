# Skill: Fail-Proof Diagnosis for Drain Annotation or Uncordon Coordination Mismatch (`14-uncordon-or-drainer-annotation`)

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
| **Lifecycle Stage** | MachineConfigPool is `Updating`, and target node is in drain or post-drain configuration phase. | Exit: `inconclusive: lifecycle_stage_not_updating` |
| **Trigger Signal** | MCC or MCD logs match: `(?i)(uncordon.*during update|desiredDrain.*lastAppliedDrain|drain.*mismatch|node.*unexpectedly schedulable|waiting for drain.*annotation)` OR Node annotations `desiredDrain` and `lastAppliedDrain` diverge while 0 drainable pods remain. | Exit: `not_supported: no_drain_coordination_error_logged` |

---

## 2. Step-by-Step Diagnostic Procedure (Deterministic Decision Tree)

```
                            [Start: Unified Splunk Dossier Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [Step 1: Extract Node Coordination State]     [No Coordination Error]
            Node name, spec.unschedulable,                ──► Exit: not_supported
            desiredDrain & lastAppliedDrain annotations
                         │
                         ▼
            [Step 2: Evaluate Schedulability & Desync]
            Check spec.unschedulable vs lifecycle phase
                         │
         ┌───────────────┴───────────────────────────────┐
         ▼                                               ▼
  [spec.unschedulable == false]                 [spec.unschedulable == true]
  Node is prematurely uncordoned!               Node is cordoned.
  ──► Branch 3A: External Uncordon              Compare desiredDrain vs lastAppliedDrain
                                                         │
                         ┌───────────────────────────────┴───────────────────────────────┐
                         ▼                                                               ▼
            [desiredDrain == lastAppliedDrain]                              [desiredDrain != lastAppliedDrain]
            Drain is officially complete!                                   Check pods remaining on node
            Handoff to 12-mcd-apply / 13-os-reboot                                           │
                                                         ┌───────────────────────────────────┴───────────────────────────────────┐
                                                         ▼                                                                       ▼
                                              [0 Drainable Pods Remain]                                               [Pods Still Evicting/Stuck]
                                              Drain completed but annotation dropped!                                 Legitimate drain in progress.
                                              ──► Branch 3B: Annotation Desync (API 409)                              Handoff to 01, 03, or 04
```

### Step 1: Extract Node Coordination State
1. In `k8s_objects` / KV Store, lookup the target `Node` object:
   * Record `spec.unschedulable` (boolean).
   * Record annotation `machineconfiguration.openshift.io/desiredDrain`.
   * Record annotation `machineconfiguration.openshift.io/lastAppliedDrain`.
2. Extract MCC and MCD logs from `index=ocp_logs`:
   * Look for optimistic locking conflicts: `(?i)Operation cannot be fulfilled on nodes.*the object has been modified`.
   * Look for MCD wait states: `(?i)waiting for node to drain.*lastAppliedDrain`.
   * Look for premature uncordon alerts: `(?i)node.*became schedulable during update`.

### Step 2: Differentiate External Uncordon vs. Annotation Desync
1. **Check Schedulability Flag:**
   * If `spec.unschedulable == false` (or not present) while `desiredDrain` is non-empty and update is in-flight:
     * **Premature Uncordon Confirmed.** Proceed to **Branch 3A**.
2. **Check Annotation Equivalence:**
   * If `desiredDrain == lastAppliedDrain`:
     * Drain coordination is fully synchronized. The stall is NOT in drain coordination. Handoff to `use-cases/12-mcd-config-render-apply` (Ignition apply failure) or `use-cases/13-os-pivot-reboot-failure`.
   * If `desiredDrain != lastAppliedDrain`:
     * Scan `k8s_objects` / KV Store for running non-daemonset pods assigned to `spec.nodeName == target_node`:
       * If **0 drainable pods remain**: Pod eviction is finished, but MCC failed to persist `lastAppliedDrain`. Proceed to **Branch 3B**.
       * If **drainable pods are still present**: Eviction or termination is still blocked by workloads. Handoff to `use-cases/01-pdb-eviction-blocked`, `use-cases/03-pod-termination-finalizer`, or `use-cases/04-storage-unmount-detach`.

---

## 3. Causal Sub-Tree Analysis (The Root-Cause Engine)

```
                            [Drain Coordination Mismatch]
                                          │
            ┌─────────────────────────────┼─────────────────────────────┐
            ▼                             ▼                             ▼
  [Branch 3A: External Uncordon] [Branch 3B: Annotation Desync] [Branch 3C: Forged Annotation]
  Autoscaler/Admin uncordoned    MCC 409 Conflict / dropped     lastAppliedDrain set manually
  node while update in flight    write after drain finished     while pods were still running
            │                             │                             │
            ▼                             ▼                             ▼
  Playbook: reconcile_drain_     Playbook: reconcile_drain_     Playbook: null (Data Risk)
  annotation (Re-cordon node)    annotation (Sync annotation)   CLI Fallback: Emergency Halt
```

* **Branch 3A: Premature Uncordon by External Actor or Competing Automation**
  * *Evidence:* `spec.unschedulable == false`, newly created pods scheduled onto the node after update started, and MCC logs report `node became schedulable during update`.
  * *Diagnosis:* An external actor (e.g. cluster autoscaler, automated node maintenance script, or manual admin intervention) executed `oc adm uncordon` during an active MCO rollout, creating a race condition where workloads land on a node undergoing OS pivot or reboot.
  * *Remediation Route:* **Clean Playbook Match $\rightarrow$ `playbook_reconcile_drain_annotation`**. (Re-cordons the node to prevent additional pod scheduling and triggers MCC reconciliation).

* **Branch 3B: Annotation Desync / API Concurrency Drop (`409 Conflict`)**
  * *Evidence:* `desiredDrain != lastAppliedDrain`, but count of non-daemonset pods on the node is exactly 0. `ocp_logs` show MCC logged `drain complete for node`, but a subsequent node update failed with `409 Conflict` or etcd context timeout. MCD is indefinitely logging `waiting for drain`.
  * *Diagnosis:* The node has successfully emptied, but the coordination flag `lastAppliedDrain` was never written to the API server due to an optimistic concurrency collision, leaving MCD in a permanent wait loop.
  * *Remediation Route:* **Clean Playbook Match $\rightarrow$ `playbook_reconcile_drain_annotation`**. (Patches `lastAppliedDrain` to equal `desiredDrain`, releasing MCD to begin applying machine config).

* **Branch 3C: Forged / Premature Completion Annotation (Corrupt State)**
  * *Evidence:* `lastAppliedDrain == desiredDrain`, but live user workload pods are still actively running and writing to local disks on the node.
  * *Diagnosis:* An operator or automation forcibly forged `lastAppliedDrain` without draining the node, endangering application integrity as MCD initiates reboot.
  * *Remediation Route:* **CRITICAL SAFETY HALT $\rightarrow$ Manual CLI Fallback Only.** Do NOT execute playbooks.

---

## 4. Remediation Resolution Rules

### Rule 1: Automated Playbook Match (`playbook_reconcile_drain_annotation`)
**Conditions for Match:**
1. Branch 3A (node uncordoned prematurely while update in-flight) OR Branch 3B (0 drainable pods remain, but `lastAppliedDrain != desiredDrain`).
2. Node is part of an active, unpaused `MachineConfigPool`.
3. No active storage corruption or forged annotation detected.

**Generated Output Spec:**
```json
{
  "matched": true,
  "playbook_id": "playbook_reconcile_drain_annotation",
  "playbook_file": "playbooks/remediate-drain-annotation.yml",
  "risk_level": "low",
  "requires_approval": true,
  "aap_extra_vars": {
    "target_cluster": "{{ cluster_id }}",
    "draining_node": "{{ node_name }}",
    "expected_mco_drain_state": "{{ desired_drain_hash }}",
    "action": "reconcile_and_cordon"
  },
  "verification_goal": "node_desired_drain == node_last_applied_drain and spec.unschedulable == true"
}
```

---

### Rule 2: Manual CLI Fallback Generation (Branch 3C or Complex Competing Automation)
**Triggered when:** Live workloads are running while annotations indicate completion, or persistent external controllers continuously toggle `spec.unschedulable`.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Live workloads detected on node despite completion annotation; emergency human intervention required.",
  "manual_cli_fallback": {
    "risk_level": "high",
    "pre_checks": [
      "# 1. Check current node cordoning and MCO drain annotations:",
      "oc get node {{ node_name }} -o jsonpath='Schedulable: {.spec.unschedulable}{\"\\n\"}Desired: {.metadata.annotations.machineconfiguration\\.openshift\\.io/desiredDrain}{\"\\n\"}Applied: {.metadata.annotations.machineconfiguration\\.openshift\\.io/lastAppliedDrain}{\"\\n\"}'",
      "# 2. Check for running pods that should have been drained:",
      "oc get pods -A --field-selector spec.nodeName={{ node_name }} -o wide"
    ],
    "remediation_steps": [
      "# 3. Immediately re-cordon the node to halt new scheduling:",
      "oc adm cordon {{ node_name }}",
      "# 4. Identify and disable competing automation controllers toggling node schedulability:",
      "oc get events -n default --field-selector involvedObject.name={{ node_name }} | grep -Ei 'uncordon|cordon'",
      "# 5. Once competing automation is silenced, let MCC reconcile naturally or trigger node drain:",
      "oc adm drain {{ node_name }} --force --ignore-daemonsets --delete-emptydir-data"
    ],
    "safety_warning": "Never manually set lastAppliedDrain unless you have verified that all non-daemonset pods have finished terminating.",
    "verification": [
      "oc get node {{ node_name }} -o jsonpath='{.spec.unschedulable}'",
      "oc -n openshift-machine-config-operator logs -l k8s-app=machine-config-daemon -c machine-config-daemon --tail=50"
    ]
  }
}
```

---

## 5. Fail-Safe Stop Conditions & Uncertainty Downgrades

The agent MUST halt and report `inconclusive` or `not_supported` if any of the following occur:

1. **Telemetry Ingestion Failure:** Splunk multi-index query fails or returns HTTP 5xx. Report: `inconclusive: telemetry_backend_unavailable`.
2. **Missing Node Record:** Target node specified in alert is not found in `index=k8s_objects` or KV Store. Report: `inconclusive: node_record_missing`.
3. **MCO Release Annotation Schema Ambiguity:** On legacy or custom releases where `desiredDrain` annotation key differs from standard schema. Report: `inconclusive: unsupported_drain_annotation_schema`.
4. **Active Eviction Conflict:** Drainable pods are still failing to evict due to PDB or volume locks. Report: `not_supported: drain_in_progress_route_to_workload_skill`.

---

## 6. Post-Remediation Verification Contract

Whether executed via AAP playbook or manual CLI, recovery MUST be proven using these exact signals:

1. **Annotation Convergence:** `metadata.annotations['machineconfiguration.openshift.io/desiredDrain'] == metadata.annotations['machineconfiguration.openshift.io/lastAppliedDrain']`.
2. **Node Cordon Integrity:** `node.spec.unschedulable == true` throughout the configuration apply and reboot cycle.
3. **MCD Advancement:** MachineConfigDaemon logs in `index=ocp_logs` transition from `waiting for drain` to `Applying MachineConfig` or `rebooting node`.
