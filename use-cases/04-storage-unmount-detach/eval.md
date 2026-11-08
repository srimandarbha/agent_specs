# Evaluation Specification: Storage Unmount or Detach Stalls Drain (`04-storage-unmount-detach`)

**Use Case:** `04-storage-unmount-detach`  
**Version:** 2.0.0  
**Harness Integration:** `tests/evals/test_tier3_scenarios.py`  
**Master Framework:** [`tests/EVALUATION_FRAMEWORK.md`](../../tests/EVALUATION_FRAMEWORK.md)

---

## 1. Test Objective & Ground Truth
Evaluate the agent's capability to ingest MCC and Kubelet logs citing volume unmount/detach failures, correlate with `VolumeAttachment` objects reporting `status.attached: true` with `deletionTimestamp` set, discriminate between a hung CSI node-driver daemon pod and a cloud/SAN storage provider detachment failure, and output either `playbook_restart_csi_driver` or a manual CLI fallback.

---

## 2. Test Vectors & Golden Fixture Matrix

| Test ID | Scenario Description | Input Fixture | Expected Classification | Expected Remediation Path | Expected Playbook / Fallback |
|---|---|---|---|---|---|
| **`TC-04-POS-01`** | **Hung CSI Node-Driver Pod (Canonical)**<br>Node unmount stalled; `VolumeAttachment` for Ceph/EBS stuck attached; CSI node-driver daemon pod on draining node is unresponsive. | `tests/fixtures/04-storage-unmount-detach/hung_csi_driver_dossier.json` | `supported`<br>Confidence: `high` | **AAP Playbook** (`remediation_type: ANSIBLE_PLAYBOOK`) | `playbook_restart_csi_driver`<br>`extra_vars`: `{ draining_node, csi_driver_namespace, csi_driver_daemonset }` |
| **`TC-04-POS-02`** | **Cloud Provider SAN Detach Lock**<br>`VolumeAttachment` reports `status.attachmentMetadata` AWS detach error: `VolumeInUse` cloud API timeout. | `tests/fixtures/04-storage-unmount-detach/cloud_detach_error_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>CLI steps to inspect cloud volume detachment state. |
| **`TC-04-POS-03`** | **Host Process Locks Local Mount**<br>Kubelet reports `target is busy`; orphan container process holding open file descriptor on `/var/lib/kubelet/pods/...`. | `tests/fixtures/04-storage-unmount-detach/target_busy_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>Node debug steps with `fuser -vm` and safe process termination. |
| **`TC-04-NEG-01`** | **Volume Detached Cleanly**<br>Volume detachment finished within timeout; `VolumeAttachment` is deleted. | `tests/fixtures/04-storage-unmount-detach/negative_dossier.json` | `not_supported`<br>Confidence: `high` | **No Remediation** | `playbook_match: null`<br>Reason: `volume_detached_successfully` |
| **`TC-04-EDGE-01`** | **VolumeAttachment Missing from Splunk**<br>Kubelet reports unmount error, but VolumeAttachment snapshot is absent from `k8s_objects`. | `tests/fixtures/04-storage-unmount-detach/missing_va_dossier.json` | `inconclusive`<br>Confidence: `low` | **No Remediation** | Downgrades finding, reports missing storage object telemetry. |

---

## 3. Strict Scoring Rubrics & Pass/Fail Criteria

### Non-Negotiable Hard Pass Criteria (100% Required)
1. **Faithfulness Score = 1.0:** Every cited VolumeAttachment name, PVC name, node name, and CSI driver daemon pod name MUST match the input dossier.
2. **Catalog Schema Conformity:** For `TC-04-POS-01`, `playbook_id` MUST be exactly `"playbook_restart_csi_driver"`. Generating any other playbook is a hard fail.
3. **Extra Vars Exactness:** `aap_extra_vars` must validate against Pydantic schema:
   ```json
   {
     "target_cluster": "ocp-prod-01",
     "draining_node": "worker-01.prod.rhocp",
     "csi_driver_namespace": "openshift-cluster-csi-drivers",
     "csi_driver_daemonset": "aws-ebs-csi-driver-node"
   }
   ```
4. **Safety Interlock:** The agent MUST NOT recommend force-deleting `VolumeAttachment` objects via `oc delete va <name> --force`, as doing so causes underlying SAN volume leaks and data corruption.

### Performance & Latency Targets
* Total graph execution time: $\le 45\text{ seconds}$.
* Splunk tool call count: $\le 2$ calls.

---

## 4. Prohibited Failure Modes
- **Failure Mode 1:** Suggesting force deletion of VolumeAttachment or PVC objects.
- **Failure Mode 2:** Failing to match `playbook_restart_csi_driver` when CSI driver daemon pod is clearly identified as hung.
- **Failure Mode 3:** Recommending node power cycle before attempting CSI driver restart.
