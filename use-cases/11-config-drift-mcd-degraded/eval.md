# Evaluation Specification: Config Drift or MCD Degraded (`11-config-drift-mcd-degraded`)

**Use Case:** `11-config-drift-mcd-degraded`  
**Version:** 2.0.0  
**Harness Integration:** `tests/evals/test_tier3_scenarios.py`  
**Master Framework:** [`tests/EVALUATION_FRAMEWORK.md`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/tests/EVALUATION_FRAMEWORK.md)

---

## 1. Test Objective & Ground Truth
Evaluate the agent's capability to ingest Machine Config Daemon (MCD) error logs and node degraded conditions, discriminate between on-disk configuration drift (`/etc/... does not match expected`) and a failed host systemd unit, and output either [`playbook_restart_failed_systemd_unit`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/remediations/PLAYBOOK_CATALOG.json#L101-L117) or a guided GitOps config drift resolution runbook.

---

## 2. Test Vectors & Golden Fixture Matrix

| Test ID | Scenario Description | Input Fixture | Expected Classification | Expected Remediation Path | Expected Playbook / Fallback |
|---|---|---|---|---|---|
| **`TC-11-POS-01`** | **Failed Non-Critical Service (Canonical)**<br>MCD degraded on `worker-01`; log cites `unit chronyd.service failed`; service allowlisted in catalog. | `tests/fixtures/11-config-drift-mcd-degraded/systemd_unit_failed_dossier.json` | `supported`<br>Confidence: `high` | **AAP Playbook** (`remediation_type: ANSIBLE_PLAYBOOK`) | `playbook_restart_failed_systemd_unit`<br>`extra_vars`: `{ target_node, systemd_service_name: "chronyd" }` |
| **`TC-11-POS-02`** | **Host File Drift in /etc**<br>MCD degraded; log reports `content of file /etc/ssh/sshd_config does not match expected: unexpected modification`. | `tests/fixtures/11-config-drift-mcd-degraded/file_drift_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>CLI steps to inspect diff and revert via GitOps or touch forcefile. |
| **`TC-11-POS-03`** | **Critical Platform Daemon Drift**<br>MCD degraded because `crio.conf` was manually edited by an external script, breaking container runtime. | `tests/fixtures/11-config-drift-mcd-degraded/crio_drift_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>Node debug steps to restore canonical MachineConfig content. |
| **`TC-11-NEG-01`** | **MCD In Sync / Done**<br>MCD on node reports `InSync` or `Done`; node is not degraded. | `tests/fixtures/11-config-drift-mcd-degraded/negative_dossier.json` | `not_supported`<br>Confidence: `high` | **No Remediation** | `playbook_match: null`<br>Reason: `mcd_not_degraded` |
| **`TC-11-EDGE-01`** | **Contradictory Pool vs Node State**<br>MCP condition reports Degraded, but target node MCD is healthy and reports `Done`. | `tests/fixtures/11-config-drift-mcd-degraded/contradictory_dossier.json` | `inconclusive`<br>Confidence: `low` | **No Remediation** | Downgrades finding, requests fleet-wide node audit. |

---

## 3. Strict Scoring Rubrics & Pass/Fail Criteria

### Non-Negotiable Hard Pass Criteria (100% Required)
1. **Faithfulness Score = 1.0:** Every cited node name, drifted file path (`/etc/...`), and failed systemd unit name MUST match the input dossier.
2. **Catalog Schema Conformity:** For `TC-11-POS-01`, `playbook_id` MUST be exactly `"playbook_restart_failed_systemd_unit"`.
3. **Extra Vars Exactness:** `aap_extra_vars` must validate against Pydantic schema:
   ```json
   {
     "target_cluster": "ocp-prod-01",
     "target_node": "worker-01.prod.rhocp",
     "systemd_service_name": "chronyd"
   }
   ```
4. **Safety Interlock on Forcefiles:** The agent MUST NOT recommend blindly running `touch /run/machine-config-daemon-force` without explicitly providing commands to diff the on-disk file against the expected rendered MachineConfig.

### Performance & Latency Targets
* Total graph execution time: $\le 45\text{ seconds}$.
* Splunk tool call count: $\le 2$ calls.

---

## 4. Prohibited Failure Modes
- **Failure Mode 1:** Recommending a node reboot when on-disk file drift is active (will trigger Greenboot boot loop).
- **Failure Mode 2:** Failing to match `playbook_restart_failed_systemd_unit` for an allowlisted failed systemd unit.
- **Failure Mode 3:** Recommending deleting the MachineConfig object from the cluster.
