# Design: API Server or ETCD Latency Prevents Drain Progress

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Design Objective
Diagnose **api server or etcd latency prevents drain progress**, isolate whether the bottleneck is master node disk I/O fsync latency, etcd database fragmentation/quota saturation, or API server admission webhook delays, and generate a deterministic manual CLI fallback specification without direct cluster mutation.

---

## Evidence-First Flow

1. **Establish Identity & Context**
   - Cluster ID, MachineConfigPool, affected nodes, and time window.
   - Pinned OpenShift release and release-matched runbook.
2. **Confirm Lifecycle Stage**
   - Trigger signal: Multiple operations report `context deadline exceeded` or `etcdserver: request timed out`.
   - Confirm active stage is `drain` or `rollout`.
3. **Execute Federated Evidence Queries**
   - Query `query_splunk_dossier` for `index=ocp_logs` and `index=k8s_objects` / KV Store; query metrics separately through Prometheus MCP.
4. **Causal Correlation & Classification**
   - Inspect cluster-wide error footprint: timeouts affecting multiple nodes/namespaces simultaneously.
   - Query Prometheus metrics: `etcd_disk_wal_fsync_duration_seconds`, `etcd_mvcc_db_total_size_in_bytes`, `apiserver_request_duration_seconds`.
   - Traverse causal sub-tree:
     - Branch 3A: `etcd_disk_wal_fsync_duration_seconds > 0.01s`? Master storage I/O latency.
     - Branch 3B: etcd database size approaching 8GB quota? Database fragmentation.
     - Branch 3C: Slow mutating webhooks on eviction subresource? Webhook saturation.
5. **Remediation Matching**
   - Automated remediation strictly prohibited (`matched: false`).
   - Generate targeted manual `oc` CLI fallback with sequential etcd defragmentation or master disk I/O audit steps.
6. **Persist & Verify**
   - Record investigation state and evidence IDs in PostgreSQL (`db/migrations/001_initial.sql`).
   - Monitor for recovery post-execution: fsync latency <= 10ms, ClusterOperators report healthy, MCC drain resumes.

---

## State Model
`TRIGGERED -> CONTEXT_CAPTURED -> EVIDENCE_COLLECTED -> ROOT_CAUSE_DIAGNOSED -> REMEDIATION_MATCHED (Manual CLI Fallback) -> PERSISTED`

---

## Data Contract
* **Investigation Record:** `investigation_id`, `cluster_id`, `affected_nodes[]`, `fsync_p99_seconds`, `etcd_db_size_bytes`, `apiserver_latency_seconds`.
* **Evidence Citations:** `mcc_timeout_log_excerpt`, `etcd_metric_snapshot`, `co_etcd_status`.
* **Remediation Specification:**
  * `{ manual_cli_commands: [ ... ], safety_warnings: "...", rollback_steps: "..." }`.

---

## Guardrails
- Strictly read-only execution in the diagnostic agent.
- NEVER reboot master nodes or mutate etcd quorum autonomously.
- Secret and credential values are stripped before persistence.
