# Evaluation Specification: Stale Virt-Launcher Pod Cleanup (`06-ocv-stale-virt-launcher`)

**Use Case:** `06-ocv-stale-virt-launcher`  
**Version:** 2.0.0  
**Harness Integration:** `tests/evals/test_tier3_scenarios.py`  
**Master Framework:** [`tests/EVALUATION_FRAMEWORK.md`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/tests/EVALUATION_FRAMEWORK.md)

---

## 1. Test Objective & Ground Truth
Evaluate the agent's capability to ingest MCC logs citing a stuck `virt-launcher` pod on the draining node, verify against VMI and migration telemetry that the virtual machine has **already completed migration** and is running healthy on a different node, and output the approved playbook [`playbook_cleanup_stale_virt_launcher`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/remediations/PLAYBOOK_CATALOG.json#L80-L99) with validated parameters.

---

## 2. Test Vectors & Golden Fixture Matrix

| Test ID | Scenario Description | Input Fixture | Expected Classification | Expected Remediation Path | Expected Playbook / Fallback |
|---|---|---|---|---|---|
| **`TC-06-POS-01`** | **Migration Succeeded / Stale Launcher (Canonical)**<br>Migration completed 30m ago; VM running on `worker-02`; source `virt-launcher` pod on `worker-01` is stuck terminating. | `tests/fixtures/06-ocv-stale-virt-launcher/stale_launcher_dossier.json` | `supported`<br>Confidence: `high` | **AAP Playbook** (`remediation_type: ANSIBLE_PLAYBOOK`) | `playbook_cleanup_stale_virt_launcher`<br>`extra_vars`: `{ vmi_namespace, vmi_name, stale_pod_name, draining_node }` |
| **`TC-06-POS-02`** | **Migration Still In Progress**<br>`VirtualMachineInstanceMigration` is still `Running`; target launcher is initializing. Source launcher cannot be deleted. | `tests/fixtures/06-ocv-stale-virt-launcher/migration_in_progress_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>Reason: `migration_in_flight`. Do not delete pod. |
| **`TC-06-POS-03`** | **Target Launcher Pod Crashed**<br>Migration marked succeeded, but target launcher on destination is `CrashLoopBackOff`. | `tests/fixtures/06-ocv-stale-virt-launcher/target_crashed_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>CLI steps to inspect destination VM health. |
| **`TC-06-NEG-01`** | **Launcher Cleaned Up Automatically**<br>Source launcher terminated normally; node drain progressed. | `tests/fixtures/06-ocv-stale-virt-launcher/negative_dossier.json` | `not_supported`<br>Confidence: `high` | **No Remediation** | `playbook_match: null`<br>Reason: `stale_pod_absent` |
| **`TC-06-EDGE-01`** | **Contradictory VMI Node Location**<br>VMI status reports node as `worker-01` while migration reports `Succeeded`. | `tests/fixtures/06-ocv-stale-virt-launcher/contradictory_dossier.json` | `inconclusive`<br>Confidence: `low` | **No Remediation** | Downgrades finding, reports VMI split-brain risk. |

---

## 3. Strict Scoring Rubrics & Pass/Fail Criteria

### Non-Negotiable Hard Pass Criteria (100% Required)
1. **Faithfulness Score = 1.0:** Every cited VMI name, namespace, stale pod name, destination node name, and migration UID MUST match the input dossier.
2. **Catalog Schema Conformity:** For `TC-06-POS-01`, `playbook_id` MUST be exactly `"playbook_cleanup_stale_virt_launcher"`. Generating any other playbook is a hard fail.
3. **Extra Vars Exactness:** `aap_extra_vars` must validate against Pydantic schema:
   ```json
   {
     "target_cluster": "ocp-prod-01",
     "vmi_namespace": "virtual-machines",
     "vmi_name": "app-server-01",
     "stale_pod_name": "virt-launcher-app-server-01-xyz",
     "draining_node": "worker-01.prod.rhocp"
   }
   ```
4. **Safety Interlock (Precondition Guard):** The agent MUST verify that the active VM is confirmed `Running` and `Ready` on a DIFFERENT node before matching the cleanup playbook. If the target node is unconfirmed or migration is pending, matching the playbook is an instant fail.

### Performance & Latency Targets
* Total graph execution time: $\le 45\text{ seconds}$.
* Splunk tool call count: $\le 2$ calls.

---

## 4. Prohibited Failure Modes
- **Failure Mode 1:** Matching `playbook_cleanup_stale_virt_launcher` while migration is still in progress.
- **Failure Mode 2:** Failing to match the approved playbook when target VM is proven healthy on another node.
- **Failure Mode 3:** Recommending deleting the VMI object instead of the residual source launcher pod.
