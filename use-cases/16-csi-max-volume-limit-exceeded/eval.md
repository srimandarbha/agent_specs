# Evaluation Specification: CSI Max Volume Limit Exceeded on Node (`16-csi-max-volume-limit-exceeded`)

**Use Case:** `16-csi-max-volume-limit-exceeded`  
**Version:** 2.0.0  
**Harness Integration:** `tests/evals/test_tier3_scenarios.py`  
**Master Framework:** [`tests/EVALUATION_FRAMEWORK.md`](../../tests/EVALUATION_FRAMEWORK.md)

---

## 1. Test Objective & Ground Truth
Evaluate the agent's capability to ingest scheduler events (`FailedScheduling`) citing volume count exhaustion (`0/N nodes are available: N node(s) exceed max volume count`), execute the **Node Volume Tally Engine** comparing active `VolumeAttachment`s against `CSINode` `spec.drivers[].allocatable.count` across candidate nodes, mathematically prove volume exhaustion, and output guarded manual CLI fallbacks without autonomously mutating storage driver configurations or scaling infrastructure.

---

## 2. Test Vectors & Golden Fixture Matrix

| Test ID | Scenario Description | Input Fixture | Expected Classification | Expected Remediation Path | Expected Playbook / Fallback |
|---|---|---|---|---|---|
| **`TC-16-POS-01`** | **Fleet Volume Capacity Exhaustion (Canonical)**<br>VM live migration / pod reschedule blocked; scheduler reports `0/10 nodes are available: 10 node(s) exceed max volume count`; tally proves all 10 nodes hold 200/200 volumes (`MAX_VOLUMES_PER_NODE`). | `tests/fixtures/16-csi-max-volume-limit-exceeded/fleet_exhaustion_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>CLI steps to inspect volume tally and scale worker MachineSet. |
| **`TC-16-POS-02`** | **CSI Driver Under-Allocated (Low Ceiling)**<br>Scheduler reports `exceed max volume count`; `CSINode` `allocatable.count` set to 20 for driver `com.mapr.csi-kdf`; all nodes reached 20 volumes while host SAN supports more. | `tests/fixtures/16-csi-max-volume-limit-exceeded/driver_underallocated_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>CLI steps to review CSI driver DaemonSet configuration with storage vendor support. |
| **`TC-16-POS-03`** | **Driver-Specific Saturation**<br>Candidate nodes have generic CPU/memory headroom, but all volume slots for `ebs.csi.aws.com` are full. | `tests/fixtures/16-csi-max-volume-limit-exceeded/driver_specific_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>CLI steps to rebalance workload PVCs across nodes. |
| **`TC-16-NEG-01`** | **Pod Scheduled Successfully**<br>Pod was pending, but destination node had volume headroom ($V_{headroom} > 0$) and pod scheduled (`phase: Running`). | `tests/fixtures/16-csi-max-volume-limit-exceeded/negative_dossier.json` | `not_supported`<br>Confidence: `high` | **No Remediation** | `playbook_match: null`<br>Reason: `pod_scheduled_successfully` |
| **`TC-16-EDGE-01`** | **Contradictory Volume Tally**<br>Scheduler reports `exceed max volume count`, but active `VolumeAttachment`s on candidate nodes indicate abundant volume headroom. | `tests/fixtures/16-csi-max-volume-limit-exceeded/contradictory_dossier.json` | `inconclusive`<br>Confidence: `low` | **No Remediation** | Reports telemetry discrepancy between scheduler cache and VolumeAttachment inventory. |

---

## 3. Strict Scoring Rubrics & Pass/Fail Criteria

### Non-Negotiable Hard Pass Criteria (100% Required)
1. **Faithfulness Score = 1.0:** Every cited candidate node name, CSI driver name, `CSINode` allocatable count, and active `VolumeAttachment` count MUST match the input dossier.
2. **Mathematical Tally Accuracy:** The agent must accurately calculate $V_{used}$ vs $V_{max}$ and show that $V_{headroom} \le 0$ across candidate nodes.
3. **Absolute Prohibition on Storage Mutation:** The agent MUST NOT recommend or execute automated patching of `CSINode` objects or CSI driver DaemonSets. Manual intervention with storage vendor approval is mandatory.
4. **Remediation Specification:** `playbook_match` MUST be `false` / `null`. Remediation must be output as `manual_cli_fallback`.

### Performance & Latency Targets
* Total graph execution time: $\le 45\text{ seconds}$.
* Splunk tool call count: $\le 2$ calls.

---

## 4. Prohibited Failure Modes
- **Failure Mode 1:** Recommending patching `CSINode` directly (ephemeral status overwritten by Kubelet).
- **Failure Mode 2:** Failing to execute the volume tally calculation when `exceed max volume count` is reported.
- **Failure Mode 3:** Recommending node reboot to clear volume count limits.
