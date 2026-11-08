# Implementation Plan: API Server or ETCD Latency Prevents Drain Progress

## Phase 0: Ground Truth & Telemetry Alignment
- [ ] Pin supported OpenShift release(s) and obtain matching MCO source/runbook revision.
- [ ] Align trigger signals in Splunk: Multiple MCC/MCD logs report `context deadline exceeded` or `etcdserver: request timed out`.
- [ ] Confirm `index=ocp_logs`, `index=k8s_objects` (with `managedFields` stripped), and `index=ocp_metrics` (`etcd_disk_wal_fsync_duration_seconds`) are populated.
- [ ] Verify that `Node`, `Lease`, and `ClusterOperator` records are cached in the Splunk KV Store (`k8s_live_inventory_lookup`) for instant retrieval.

## Phase 1: Read-Only Evidence Tooling
- [ ] Implement the parameterized **Unified Multi-Index Splunk Search** (`query_unified_splunk_dossier`).
- [ ] Bound search time: `earliest=-1h latest=now` for logs/metrics; `earliest=-24h` for objects (or instant KV Store lookup).
- [ ] Normalize timestamps, cluster ID, and control-plane metric quantiles into structured state.
- [ ] Redact secrets, authorization headers, and environment variables.

## Phase 2: Causal Reasoning & Classification
- [ ] Extract error frequency and node scope from MCC logs.
- [ ] Query Prometheus metrics for 99th percentile WAL fsync latency and etcd DB physical size.
- [ ] **Multi-level Root Cause Analysis:**
  - Is master node underlying disk latency exceeding 10ms (`etcd_disk_wal_fsync_duration_seconds > 0.01`)?
  - Is the etcd database approaching the 8GB quota due to lack of compaction?
  - Are admission webhooks injecting latency into eviction requests while etcd disk is fast?

## Phase 3: Two-Tier Remediation & Playbook Matching
- [ ] **Catalog Matching:** Evaluate against [`remediations/PLAYBOOK_CATALOG.json`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/remediations/PLAYBOOK_CATALOG.json):
  - Autonomous mutation of etcd or master nodes is **strictly prohibited** (`matched: false`).
- [ ] **Intelligent CLI Fallback:**
  - For disk fsync latency: output master host disk I/O audit runbook.
  - For database fragmentation: output sequential, member-by-member `etcdctl defrag` runbook with strict pause intervals.
  - For webhook delays: output mutating webhook configuration audit commands.
- [ ] Keep all mutation tools disabled inside the agent; hand off execution to certified platform administrators.

## Phase 4: Verification & Acceptance Tests
- [ ] Unit tests: matching trigger, non-matching trigger, incomplete evidence, and contradictory evidence.
- [ ] Graph test: single multi-index query completes within 10s; graph completes within 45s deadline.
- [ ] Isolation test: single worker node timeout with healthy etcd correctly reports `not_supported`.
- [ ] Safety test: verify agent strictly refuses autonomous control-plane restarts.
- [ ] Post-remediation verification: `etcd_disk_wal_fsync_duration_seconds <= 0.01`, ClusterOperators healthy, and MCC drain resumes.

---

## Observability & Graph Integration Contract

### Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Controller drain logs, etcd logs, kube-apiserver logs.
* `index=k8s_objects` / KV Store: `Node`, `Lease` in `kube-node-lease`, `ClusterOperator`.
* `index=ocp_metrics`: `etcd_disk_wal_fsync_duration_seconds`, `etcd_mvcc_db_total_size_in_bytes`, `apiserver_request_duration_seconds`.

### Bounded Execution
* Max 2 Splunk tool calls total per investigation.
* 15-second per-query timeout; 45-second overall investigation deadline.
* Stop as `inconclusive` if cluster identity is ambiguous or required telemetry is unavailable.
