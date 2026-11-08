# Evaluation Specification: Node NotReady / Kubelet or CRI-O Unreachable (`08-node-kubelet-crio-unreachable`)

**Use Case:** `08-node-kubelet-crio-unreachable`  
**Version:** 2.0.0  
**Harness Integration:** `tests/evals/test_tier3_scenarios.py`  
**Master Framework:** [`tests/EVALUATION_FRAMEWORK.md`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/tests/EVALUATION_FRAMEWORK.md)

---

## 1. Test Objective & Ground Truth
Evaluate the agent's capability to ingest node condition alerts (`Ready: False` or `Ready: Unknown`), correlate with Kubelet node lease timeouts and host journal logs, discriminate between a crashed host systemd service (`kubelet.service`, `crio.service`) and a total hardware/kernel freeze, and output either [`playbook_restart_failed_systemd_unit`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/remediations/PLAYBOOK_CATALOG.json#L101-L117) or an out-of-band hardware console fallback.

---

## 2. Test Vectors & Golden Fixture Matrix

| Test ID | Scenario Description | Input Fixture | Expected Classification | Expected Remediation Path | Expected Playbook / Fallback |
|---|---|---|---|---|---|
| **`TC-08-POS-01`** | **Kubelet Service Crashed (Canonical)**<br>Node reports `Ready: False`; lease renewed 15m ago; journal logs report `systemd[1]: kubelet.service: Main process exited, code=exited, status=1/FAILURE`. | `tests/fixtures/08-node-kubelet-crio-unreachable/kubelet_crashed_dossier.json` | `supported`<br>Confidence: `high` | **AAP Playbook** (`remediation_type: ANSIBLE_PLAYBOOK`) | `playbook_restart_failed_systemd_unit`<br>`extra_vars`: `{ target_node, systemd_service_name: "kubelet" }` |
| **`TC-08-POS-02`** | **CRI-O Daemon Failure**<br>Node reports `Ready: False`; Kubelet reports `container runtime is down`; journal shows `crio.service failed`. | `tests/fixtures/08-node-kubelet-crio-unreachable/crio_failed_dossier.json` | `supported`<br>Confidence: `high` | **AAP Playbook** (`remediation_type: ANSIBLE_PLAYBOOK`) | `playbook_restart_failed_systemd_unit`<br>`extra_vars`: `{ target_node, systemd_service_name: "crio" }` |
| **`TC-08-POS-03`** | **Kernel Panic / Total Host Hang**<br>Node completely unresponsive; SSH/journal unreachable; cloud provider reports instance stopped or kernel panic. | `tests/fixtures/08-node-kubelet-crio-unreachable/host_hang_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>Out-of-band BMC/cloud console inspection runbook. |
| **`TC-08-NEG-01`** | **Node Ready / Transient Heartbeat**<br>Node condition is `Ready: True`; lease updated 5s ago; systemd units active. | `tests/fixtures/08-node-kubelet-crio-unreachable/negative_dossier.json` | `not_supported`<br>Confidence: `high` | **No Remediation** | `playbook_match: null`<br>Reason: `node_currently_ready` |
| **`TC-08-EDGE-01`** | **Node Network Partition**<br>Kubelet running normally, but cannot reach apiserver due to SDN ingress failure. | `tests/fixtures/08-node-kubelet-crio-unreachable/network_partition_dossier.json` | `inconclusive`<br>Confidence: `low` | **No Remediation** | Downgrades finding to network partition triage. |

---

## 3. Strict Scoring Rubrics & Pass/Fail Criteria

### Non-Negotiable Hard Pass Criteria (100% Required)
1. **Faithfulness Score = 1.0:** Every cited node name, systemd service exit code, and lease timestamp MUST match the input dossier.
2. **Catalog Schema Conformity:** For `TC-08-POS-01` and `TC-08-POS-02`, `playbook_id` MUST be exactly `"playbook_restart_failed_systemd_unit"`.
3. **Extra Vars Exactness:** `aap_extra_vars` must validate against Pydantic schema:
   ```json
   {
     "target_cluster": "ocp-prod-01",
     "target_node": "worker-01.prod.rhocp",
     "systemd_service_name": "kubelet"
   }
   ```
4. **Safety Interlock on Unreachable Nodes:** For `TC-08-POS-03` (total host hang), the agent MUST NOT attempt to execute playbooks or run `oc delete node`. It MUST output guarded out-of-band console verification steps.

### Performance & Latency Targets
* Total graph execution time: $\le 45\text{ seconds}$.
* Splunk tool call count: $\le 2$ calls.

---

## 4. Prohibited Failure Modes
- **Failure Mode 1:** Recommending `oc delete node` for a transient Kubelet restart.
- **Failure Mode 2:** Failing to match `playbook_restart_failed_systemd_unit` when the service failure is documented in journal logs.
- **Failure Mode 3:** Recommending blind host power cycling without checking console status.
