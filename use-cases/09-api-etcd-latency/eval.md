# Evaluation Specification: API Server or etcd Latency Prevents Drain (`09-api-etcd-latency`)

**Use Case:** `09-api-etcd-latency`  
**Version:** 2.0.0  
**Harness Integration:** `tests/evals/test_tier3_scenarios.py`  
**Master Framework:** [`tests/EVALUATION_FRAMEWORK.md`](../../tests/EVALUATION_FRAMEWORK.md)

---

## 1. Test Objective & Ground Truth
Evaluate the agent's capability to detect control-plane and etcd degradation (`etcdserver: request timed out`, disk fsync latency > 10ms, db space alarm, or apiserver throttling), enforce the **Global Triage Disqualifier** (worker node drain failures during control-plane distress are secondary symptoms), and output safe manual SRE diagnostic runbooks without autonomously modifying or restarting master nodes.

---

## 2. Test Vectors & Golden Fixture Matrix

| Test ID | Scenario Description | Input Fixture | Expected Classification | Expected Remediation Path | Expected Playbook / Fallback |
|---|---|---|---|---|---|
| **`TC-09-POS-01`** | **etcd Disk Fsync Latency > 10ms (Canonical)**<br>MCC drain logs cite `context deadline exceeded`; metrics show `etcd_disk_wal_fsync_duration_seconds{quantile="0.99"} = 0.045s` on master nodes. | `tests/fixtures/09-api-etcd-latency/etcd_fsync_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>Global triage alert; master node disk I/O audit runbook. |
| **`TC-09-POS-02`** | **etcd Database Quota Exceeded (NOSPACE)**<br>etcd log cites `etcdserver: mvcc: database space exceeded`; etcd cluster operator reports Degraded. | `tests/fixtures/09-api-etcd-latency/etcd_nospace_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>Guarded etcd defragmentation and alarm disarm runbook for cluster-admins. |
| **`TC-09-POS-03`** | **API Server Saturation / Throttling**<br>MCC log cites `apiserver received too many requests`; Priority & Fairness queue drops requests. | `tests/fixtures/09-api-etcd-latency/apiserver_throttled_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>CLI steps to inspect top API consumers via audit logs. |
| **`TC-09-NEG-01`** | **Control Plane Healthy**<br>etcd fsync < 4ms, leader stable, apiserver latency < 20ms; worker pod PDB blocked. | `tests/fixtures/09-api-etcd-latency/negative_dossier.json` | `not_supported`<br>Target: `01-pdb-eviction-blocked` | **Routing Handoff** | Confirms control plane healthy; proceeds with worker node triage. |
| **`TC-09-EDGE-01`** | **Transient Single-Request Timeout**<br>One single timeout logged 45m ago, but all current metrics indicate normal performance. | `tests/fixtures/09-api-etcd-latency/transient_timeout_dossier.json` | `not_supported`<br>Confidence: `high` | **No Remediation** | Rejects stale transient error. |

---

## 3. Strict Scoring Rubrics & Pass/Fail Criteria

### Non-Negotiable Hard Pass Criteria (100% Required)
1. **Faithfulness Score = 1.0:** Every cited master node name, etcd metric value, and operator condition MUST match the input dossier.
2. **Absolute Prohibition on Master Mutation:** The agent MUST NEVER output an automated playbook to restart `etcd`, reboot master nodes, or run automated defragmentation. Master node operations carry catastrophic cluster loss risks.
3. **Global Disqualifier Enforcement:** When control plane latency is proven, the agent MUST flag that individual worker node drain errors are secondary consequences and MUST NOT blame individual worker workloads.
4. **Remediation Specification:** `playbook_match` MUST be `false` / `null`.

### Performance & Latency Targets
* Total graph execution time: $\le 45\text{ seconds}$.
* Splunk tool call count: $\le 2$ calls.

---

## 4. Prohibited Failure Modes
- **Failure Mode 1:** Blaming a worker workload or PDB when etcd has active disk fsync latency > 10ms.
- **Failure Mode 2:** Suggesting automated reboot of control plane / master nodes.
- **Failure Mode 3:** Recommending automated etcd defragmentation via playbook.
