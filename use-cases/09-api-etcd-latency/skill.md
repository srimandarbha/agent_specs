# Skill: Fail-Proof Diagnosis for API Server or ETCD Latency Blocking Drain (`09-api-etcd-latency`)

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
| **Lifecycle Stage** | MachineConfigPool update is active or MCO operations are stalling across multiple nodes. | Exit: `inconclusive: lifecycle_stage_not_updating` |
| **Trigger Signal** | MCC or operator logs match: `(?i)(context deadline exceeded|etcdserver: request timed out|etcdserver: leader changed|apiserver.*timeout|Client\.Timeout exceeded while awaiting headers)` OR Prometheus metrics report `etcd_disk_wal_fsync_duration_seconds{quantile="0.99"} > 0.01` OR ClusterOperator `etcd` or `kube-apiserver` condition `Degraded` is `True`. | Exit: `not_supported: control_plane_latency_within_thresholds` |

---

## 2. Step-by-Step Diagnostic Procedure (Deterministic Decision Tree)

```
                            [Start: Unified Splunk Dossier Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [Step 1: Check Control Plane Metrics]         [Control Plane Healthy]
            etcd fsync, apiserver latency, CO status      ──► Exit: not_supported
                         │
                         ▼
            [Step 2: Differentiate Storage vs DB vs Webhook]
            Evaluate WAL fsync, DB quota, and API saturation
                         │
         ┌───────────────┼───────────────────────────────┐
         ▼               ▼                               ▼
  [WAL fsync > 10ms]     [DB Size > 6GB / Quota]         [API Webhook Saturation]
  etcd disk write I/O    Database fragmentation or       etcd disk is fast (<5ms);
  latency on master host space exhaustion                Admission webhook delay
         │                       │                               │
         ▼                       ▼                               ▼
  Branch 3A: Disk I/O    Branch 3B: ETCD Defrag          Branch 3C: Webhook / APF
  Bottleneck             Runbook Required                Saturation
```

### Step 1: Check Control Plane Metrics & Cluster-Wide Scope
1. Query `index=ocp_metrics` for etcd performance indicators:
   * `etcd_disk_wal_fsync_duration_seconds{quantile="0.99"}`:
     * If `> 0.01s` (10ms): Master host storage cannot flush write-ahead logs fast enough.
   * `etcd_disk_backend_commit_duration_seconds{quantile="0.99"}`:
     * If `> 0.025s` (25ms): Backend B-tree commit delays detected.
   * `etcd_mvcc_db_total_size_in_bytes`:
     * If `> 6442450944` (> 6GB towards 8GB limit): Database approaching storage quota.
2. Query `index=ocp_logs` for MCC controller logs:
   * Determine error distribution: Are API timeouts occurring on only one node, or spanning multiple worker nodes and namespaces?
   * If errors affect multiple unrelated worker nodes simultaneously, confirm **Cluster Control Plane Incident**.

### Step 2: Differentiate etcd Disk vs. Database Fragmentation vs. Webhook Latency
1. **Case 2A: etcd Disk WAL fsync Latency:**
   * If WAL fsync 99th percentile > 10ms or etcd logs report:
     ```regex
     (?i)took too long \((?<latency_ms>\d+)ms\) to execute disk fsync
     ```
   * Proceed to **Branch 3A**.
2. **Case 2B: etcd Database Space Quota / Fragmentation:**
   * If etcd logs report `database space exceeded` or metric `etcdDatabaseQuotaLowSpace` is firing:
   * Proceed to **Branch 3B**.
3. **Case 2C: API Server Saturation / Mutating Webhook Deadlock:**
   * If etcd disk latency is low (< 5ms), but `apiserver_request_duration_seconds{subresource="eviction"}` > 5s with admission webhook errors:
   * Proceed to **Branch 3C**.

---

## 3. Causal Sub-Tree Analysis (The Root-Cause Engine)

```
                              [Control Plane Latency Block]
                                            │
              ┌─────────────────────────────┼─────────────────────────────┐
              ▼                             ▼                             ▼
    [Branch 3A: Disk fsync]       [Branch 3B: DB Fragmentation] [Branch 3C: Webhook Saturation]
    Master node NVMe/SAN latency  etcd DB approaching 8GB       Slow admission webhook or
    stalls raft consensus writes  quota; defrag required        FlowSchema APF throttling
              │                             │                             │
              ▼                             ▼                             ▼
    Playbook: null (Hardware)     Playbook: null (Risk)         Playbook: null (API Policy)
    CLI Fallback: Master Storage  CLI Fallback: etcdctl defrag  CLI Fallback: Webhook Triage
```

* **Branch 3A: Master Node Disk I/O / WAL fsync Latency**
  * *Evidence:* `etcd_disk_wal_fsync_duration_seconds{quantile="0.99"} > 0.01s`; etcd logs show repeated warnings: `took too long ... to execute disk fsync`. MCC drain operations time out waiting for annotation updates.
  * *Diagnosis:* Underlying storage backing the master nodes (SAN, VM datastore, or local disk) cannot deliver sustained < 10ms fsync performance required for Raft consensus.
  * *Remediation Route:* **DO NOT troubleshoot individual worker nodes.** Route to **Manual CLI Fallback (Master Storage & IOPS Audit)**.

* **Branch 3B: etcd Database Space Exhaustion / Fragmentation**
  * *Evidence:* etcd database size exceeds 6GB (approaching 8GB hard limit); alert `etcdDatabaseQuotaLowSpace` is active; etcd logs show slow bbolt compaction.
  * *Diagnosis:* Excessive historical object churn without compaction has inflated the etcd database, resulting in slow range queries and API timeouts during eviction requests.
  * *Remediation Route:* **Manual CLI Fallback (Sequential etcd defragmentation runbook)**.

* **Branch 3C: Kube-Apiserver Saturation / Mutating Admission Webhook Delay**
  * *Evidence:* etcd disk metrics are healthy (< 5ms), but eviction subresource calls time out; API server logs report mutating webhook timeouts on eviction admission.
  * *Diagnosis:* A third-party security or governance webhook is intercepting eviction requests and failing or timing out.
  * *Remediation Route:* **Manual CLI Fallback (Admission Webhook Triage)**.

---

## 4. Remediation Resolution Rules

### Absolute Safety Rule on Control Plane Components
> [!CAUTION]
> The diagnostic agent MUST NEVER execute autonomous playbooks to restart etcd pods, remove etcd cluster members, or run automated defragmentation. Control-plane mutations can cause quorum loss, leading to catastrophic multi-cluster failure. Remediation must be executed by certified platform engineers following supported Red Hat runbooks.

### Rule 1: Manual CLI Fallback Generation (Branch 3A - Master Storage Latency)
**Triggered when:** etcd WAL fsync exceeds 10ms.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "etcd disk fsync latency exceeds 10ms threshold; control-plane storage saturation confirmed.",
  "manual_cli_fallback": {
    "risk_level": "critical",
    "pre_checks": [
      "# 1. Check etcd cluster operator status:",
      "oc get co etcd -o yaml",
      "# 2. Inspect etcd member endpoint health and fsync latency:",
      "oc -n openshift-etcd rsh -c etcd $(oc -n openshift-etcd get pods -l app=etcd -o jsonpath='{.items[0].metadata.name}') etcdctl endpoint status -w table"
    ],
    "remediation_steps": [
      "# 3. Inspect master node underlying disk latency (fio / iostat):",
      "oc debug node/{{ master_node }} -- chroot /host iostat -xz 1 5",
      "# 4. Check for noisy neighbor workloads or SAN storage throttling on control-plane hosts.",
      "# 5. Once storage latency drops < 10ms, MCO drain operations will automatically succeed."
    ],
    "safety_warning": "Do not restart etcd pods or reboot master nodes while etcd is experiencing high latency without quorum validation.",
    "verification": [
      "oc get co etcd -o jsonpath='{.status.conditions[?(@.type==\"Degraded\")].status}'"
    ]
  }
}
```

---

### Rule 2: Manual CLI Fallback Generation (Branch 3B - Database Defragmentation)
**Triggered when:** etcd database size approaches quota limit.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "etcd database approaching quota limit; fragmentation blocking API write throughput.",
  "manual_cli_fallback": {
    "risk_level": "high",
    "pre_checks": [
      "# 1. Check etcd database physical size vs quota across all members:",
      "oc -n openshift-etcd rsh -c etcd $(oc -n openshift-etcd get pods -l app=etcd -o jsonpath='{.items[0].metadata.name}') etcdctl endpoint status -w table"
    ],
    "remediation_steps": [
      "# 2. Run sequential defragmentation one member at a time (wait 1 minute between nodes):",
      "for pod in $(oc -n openshift-etcd get pods -l app=etcd -o jsonpath='{.items[*].metadata.name}'); do",
      "  echo \"Defragmenting $pod...\";",
      "  oc -n openshift-etcd rsh -c etcd $pod etcdctl defrag;",
      "  sleep 60;",
      "done",
      "# 3. Verify database size reduced across all endpoints:",
      "oc -n openshift-etcd rsh -c etcd $(oc -n openshift-etcd get pods -l app=etcd -o jsonpath='{.items[0].metadata.name}') etcdctl endpoint status -w table"
    ],
    "safety_warning": "Never defragment all etcd members simultaneously; defragmentation locks the B-tree for the duration of the run.",
    "verification": [
      "oc get co etcd -o jsonpath='{.status.conditions[?(@.type==\"Degraded\")].status}'"
    ]
  }
}
```

---

## 5. Fail-Safe Stop Conditions & Uncertainty Downgrades

The agent MUST halt and report `inconclusive` or `not_supported` if any of the following occur:

1. **Telemetry Ingestion Failure:** Splunk multi-index query fails or returns HTTP 5xx. Report: `inconclusive: telemetry_backend_unavailable`.
2. **Single-Node Isolated Timeout:** MCC logs report a single transient API timeout on node-1, but etcd disk latency is < 2ms, ClusterOperators are healthy, and all other nodes update cleanly. Report: `not_supported: isolated_transient_timeout_not_systemic_control_plane_failure`.
3. **Master Pool Updating:** If master nodes themselves are undergoing MCO reboot, temporary API pauses are expected. Report: `inconclusive: master_pool_rollout_in_progress`.

---

## 6. Post-Remediation Verification Contract

Whether storage latency recovers or defragmentation is performed, recovery MUST be proven using these exact signals:

1. **etcd Metric Normalized:** `etcd_disk_wal_fsync_duration_seconds{quantile="0.99"} <= 0.01s`.
2. **ClusterOperators Available:** `kube-apiserver` and `etcd` report `Available: True`, `Degraded: False`.
3. **MCO Drain Resumes:** `index=ocp_logs` records MCC successfully evicting pods without deadline exceeded errors.
