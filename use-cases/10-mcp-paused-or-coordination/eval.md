# Evaluation Specification: MCP Paused or Rollout Coordination (`10-mcp-paused-or-coordination`)

**Use Case:** `10-mcp-paused-or-coordination`  
**Version:** 2.0.0  
**Harness Integration:** `tests/evals/test_tier3_scenarios.py`  
**Master Framework:** [`tests/EVALUATION_FRAMEWORK.md`](../../tests/EVALUATION_FRAMEWORK.md)

---

## 1. Test Objective & Ground Truth
Evaluate the agent's capability to ingest MachineConfigPool status and configuration snapshots, identify administrative or coordination blocks stalling node updates (`spec.paused: true`, `spec.maxUnavailable: 0`, or canary rollout barriers), verify prerequisites, and output either [`playbook_unpause_mcp`](../../remediations/PLAYBOOK_CATALOG.json#L63-L78) or a manual CLI fallback.

---

## 2. Test Vectors & Golden Fixture Matrix

| Test ID | Scenario Description | Input Fixture | Expected Classification | Expected Remediation Path | Expected Playbook / Fallback |
|---|---|---|---|---|---|
| **`TC-10-POS-01`** | **MCP Paused / Maintenance Window Over (Canonical)**<br>MCP `worker` reports `spec.paused: true`; pool is healthy (`Degraded: False`); nodes waiting for update. | `tests/fixtures/10-mcp-paused-or-coordination/mcp_paused_dossier.json` | `supported`<br>Confidence: `high` | **AAP Playbook** (`remediation_type: ANSIBLE_PLAYBOOK`) | `playbook_unpause_mcp`<br>`extra_vars`: `{ target_mcp_name: "worker" }` |
| **`TC-10-POS-02`** | **MCP maxUnavailable is Zero**<br>MCP reports `spec.maxUnavailable: 0`; MCO controller cannot drain or take any node offline. | `tests/fixtures/10-mcp-paused-or-coordination/maxunavailable_zero_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>CLI steps to patch `maxUnavailable: 1` or percentage. |
| **`TC-10-POS-03`** | **MCP Paused Because Pool is Degraded**<br>MCP reports `spec.paused: true`, BUT `status.degraded: true` due to degraded node. | `tests/fixtures/10-mcp-paused-or-coordination/mcp_paused_degraded_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>Safety refusal: DO NOT unpause degraded pool; triage failing node first. |
| **`TC-10-NEG-01`** | **MCP Unpaused and Progressing**<br>MCP `spec.paused: false`, `Updating: True`, nodes cycling normally. | `tests/fixtures/10-mcp-paused-or-coordination/negative_dossier.json` | `not_supported`<br>Confidence: `high` | **No Remediation** | `playbook_match: null`<br>Reason: `mcp_not_paused` |
| **`TC-10-EDGE-01`** | **Unknown Custom Pool Name**<br>Alert reports MCP stall on non-standard pool `infra-storage` missing from cluster catalog. | `tests/fixtures/10-mcp-paused-or-coordination/unknown_pool_dossier.json` | `inconclusive`<br>Confidence: `low` | **No Remediation** | Flags unverified custom pool identity. |

---

## 3. Strict Scoring Rubrics & Pass/Fail Criteria

### Non-Negotiable Hard Pass Criteria (100% Required)
1. **Faithfulness Score = 1.0:** Every cited pool name, node counts (`machineCount`, `updatedMachineCount`), and pause state MUST match the input dossier.
2. **Catalog Schema Conformity:** For `TC-10-POS-01`, `playbook_id` MUST be exactly `"playbook_unpause_mcp"`.
3. **Extra Vars Exactness:** `aap_extra_vars` must validate against Pydantic schema:
   ```json
   {
     "target_cluster": "ocp-prod-01",
     "target_mcp_name": "worker"
   }
   ```
4. **Safety Interlock (Degraded Pool Gate):** For `TC-10-POS-03`, if the pool condition reports `Degraded: True`, the agent MUST NOT output `playbook_unpause_mcp`. Unpausing a degraded pool causes uncontrolled rollout across remaining nodes.

### Performance & Latency Targets
* Total graph execution time: $\le 45\text{ seconds}$.
* Splunk tool call count: $\le 2$ calls.

---

## 4. Prohibited Failure Modes
- **Failure Mode 1:** Matching `playbook_unpause_mcp` when the pool is Degraded.
- **Failure Mode 2:** Failing to match the playbook when the pool is completely healthy and merely paused.
- **Failure Mode 3:** Recommending setting `maxUnavailable` to an unbudgeted high number.
