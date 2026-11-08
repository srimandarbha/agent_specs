# Evaluation Specification: Drain Annotation or Uncordon Mismatch (`14-uncordon-or-drainer-annotation`)

**Use Case:** `14-uncordon-or-drainer-annotation`  
**Version:** 2.0.0  
**Harness Integration:** `tests/evals/test_tier3_scenarios.py`  
**Master Framework:** [`tests/EVALUATION_FRAMEWORK.md`](../../tests/EVALUATION_FRAMEWORK.md)

---

## 1. Test Objective & Ground Truth
Evaluate the agent's capability to ingest node drain annotations (`machineconfiguration.openshift.io/desiredDrain` vs `lastAppliedDrain`) and node schedulability state (`spec.unschedulable`), detect when external actors or competing automation uncordoned the node prematurely or an annotation race condition occurred, and output [`playbook_reconcile_drain_annotation`](../../remediations/PLAYBOOK_CATALOG.json#L45-L61) with validated parameters.

---

## 2. Test Vectors & Golden Fixture Matrix

| Test ID | Scenario Description | Input Fixture | Expected Classification | Expected Remediation Path | Expected Playbook / Fallback |
|---|---|---|---|---|---|
| **`TC-14-POS-01`** | **External Actor Prematurely Uncordoned (Canonical)**<br>MCD updating node `worker-01`; human admin or CI uncordoned node (`spec.unschedulable: false`); MCC stalled because desiredDrain != lastAppliedDrain. | `tests/fixtures/14-uncordon-or-drainer-annotation/external_uncordon_dossier.json` | `supported`<br>Confidence: `high` | **AAP Playbook** (`remediation_type: ANSIBLE_PLAYBOOK`) | `playbook_reconcile_drain_annotation`<br>`extra_vars`: `{ draining_node, expected_mco_drain_state: "drain" }` |
| **`TC-14-POS-02`** | **Annotation Desync After Drain**<br>Drain succeeded, but `lastAppliedDrain` was not written due to transient apiserver disconnect; MCC stalled waiting for reconciliation. | `tests/fixtures/14-uncordon-or-drainer-annotation/annotation_desync_dossier.json` | `supported`<br>Confidence: `high` | **AAP Playbook** (`remediation_type: ANSIBLE_PLAYBOOK`) | `playbook_reconcile_drain_annotation`<br>`extra_vars`: `{ draining_node, expected_mco_drain_state: "reconciled" }` |
| **`TC-14-POS-03`** | **Competing Autoscaler / Self-Node-Remediation**<br>Self-node-remediation operator fighting MCO over cordoning state on `worker-02`. | `tests/fixtures/14-uncordon-or-drainer-annotation/competing_operator_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>CLI steps to pause competing operator before reconciling annotations. |
| **`TC-14-NEG-01`** | **Annotations in Sync**<br>`desiredDrain` matches `lastAppliedDrain`; node cordoned correctly; drain in progress. | `tests/fixtures/14-uncordon-or-drainer-annotation/negative_dossier.json` | `not_supported`<br>Confidence: `high` | **No Remediation** | `playbook_match: null`<br>Reason: `annotations_in_sync` |
| **`TC-14-EDGE-01`** | **Node Already Done and Schedulable**<br>MCO rollout finished, MCD is `Done`, node uncordoned as expected. | `tests/fixtures/14-uncordon-or-drainer-annotation/rollout_done_dossier.json` | `not_supported`<br>Confidence: `high` | **No Remediation** | Rejects false alarm. |

---

## 3. Strict Scoring Rubrics & Pass/Fail Criteria

### Non-Negotiable Hard Pass Criteria (100% Required)
1. **Faithfulness Score = 1.0:** Every cited node name, annotation values (`desiredDrain`, `lastAppliedDrain`), and `spec.unschedulable` status MUST match the input dossier.
2. **Catalog Schema Conformity:** For `TC-14-POS-01` and `TC-14-POS-02`, `playbook_id` MUST be exactly `"playbook_reconcile_drain_annotation"`.
3. **Extra Vars Exactness:** `aap_extra_vars` must validate against Pydantic schema:
   ```json
   {
     "target_cluster": "ocp-prod-01",
     "draining_node": "worker-01.prod.rhocp",
     "expected_mco_drain_state": "drain"
   }
   ```
4. **Safety Interlock:** The agent MUST NOT recommend uncordoning a node while MCD is still actively applying machine configs.

### Performance & Latency Targets
* Total graph execution time: $\le 45\text{ seconds}$.
* Splunk tool call count: $\le 2$ calls.

---

## 4. Prohibited Failure Modes
- **Failure Mode 1:** Recommending `oc adm uncordon` while MCD is in state `Applying`.
- **Failure Mode 2:** Failing to match `playbook_reconcile_drain_annotation` when drain annotations are clearly mismatched.
- **Failure Mode 3:** Recommending node reboot for an annotation mismatch.
