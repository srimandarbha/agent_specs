# SPEC: API Server or ETCD Latency Prevents Drain Progress

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Problem Statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **API server or etcd latency prevents drain progress**, isolate whether the breakdown is master node disk I/O fsync latency, etcd database space exhaustion / fragmentation, or API server request saturation from slow admission webhooks, and formulate an actionable remediation specification (manual CLI fallback) without direct cluster mutation.

## Trigger and Scope
- Lifecycle stage: **API Requests / Eviction Coordination / Control Plane**
- Trigger signal: MCC or operator logs match `(?i)(context deadline exceeded|etcdserver: request timed out|etcdserver: leader changed|apiserver.*timeout|Client\.Timeout exceeded)` across multiple worker nodes OR Prometheus metric `etcd_disk_wal_fsync_duration_seconds{quantile="0.99"} > 0.01` OR ClusterOperator `etcd` or `kube-apiserver` condition `Degraded` is `True`.
- In scope: Read-only evidence gathering from unified Splunk multi-index search/KV store, Prometheus control-plane metric evaluation, cluster-wide error correlation, disqualifying worker-node root causes, confidence reporting, safe manual CLI fallback runbook generation, and recovery verification.
- Out of scope: Autonomous etcd mutation, rebooting master nodes, or modifying etcd quorum membership from the agent.

## Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Controller drain logs, etcd server logs, kube-apiserver audit/error logs.
* `index=k8s_objects` / KV Store:
  * `Node` (`status.conditions`, `spec.unschedulable`).
  * `Lease` in `kube-node-lease` (`spec.renewTime`).
  * `MachineConfigPool` (`status.conditions`, `status.phase`).
  * `Event` (control plane and eviction timeout events).
* `index=ocp_metrics`:
  * `etcd_disk_wal_fsync_duration_seconds{quantile="0.99"}`
  * `etcd_disk_backend_commit_duration_seconds{quantile="0.99"}`
  * `etcd_mvcc_db_total_size_in_bytes`
  * `apiserver_request_duration_seconds{subresource="eviction"}`
  * `cluster_operator_conditions{name=~"kube-apiserver|etcd", condition="Degraded"}`

## Diagnostic Strategy
1. **Perception:** Ingest unified Splunk dossier in a single round-trip.
2. **Correlation:** Check cluster-wide scope: Are API timeouts and lease delays occurring across multiple nodes and namespaces?
3. **Causal Depth:** Determine the exact control plane bottleneck:
   - Does `etcd_disk_wal_fsync_duration_seconds` exceed 10ms? (Branch 3A - Master Storage I/O Latency).
   - Does `etcd_mvcc_db_total_size_in_bytes` approach the 8GB quota? (Branch 3B - Database Fragmentation).
   - Is etcd fast (< 5ms) but apiserver eviction duration is high with webhook timeouts? (Branch 3C - Webhook Saturation).

## Two-Tier Remediation Contract
1. **Playbook Matching (AAP / AWX):**
   - **Automated remediation is STRICTLY PROHIBITED** (`matched: false`). Control-plane components are mission-critical; uncoordinated restarts can lead to split-brain or total cluster quorum loss.
2. **Targeted CLI Fallback (Human SRE Runbook):**
   - For master storage latency: output master disk I/O inspection commands (`iostat`, `fio`, SAN latency checks).
   - For database fragmentation: output sequential, member-by-member `etcdctl defrag` runbook with strict pause intervals.
   - For admission webhooks: output mutating webhook configuration audit commands.

## Safety Constraints
* NEVER restart control-plane components or run automated defragmentation from the agent.
* NEVER defragment all etcd members simultaneously.
* The agent has zero direct mutation tools.

## Success Criteria
`etcd_disk_wal_fsync_duration_seconds{quantile="0.99"} <= 0.01s`, `kube-apiserver` and `etcd` report `Available: True`, `Degraded: False`, and MCC logs confirm pod evictions resume without context deadline timeouts.

---

## Agent Graph Integration Contract

This use case is invoked by the shared 10-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`.

### Bounded Execution
* Investigation Deadline: 45 seconds.
* Tool Budget: Max 2 Splunk tool calls per investigation.
* Output: Structured report with evidence citations and either an `aap_launch_spec` or `manual_cli_fallback`.
