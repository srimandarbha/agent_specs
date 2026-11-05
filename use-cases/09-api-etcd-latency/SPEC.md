# SPEC: API server or etcd latency prevents drain progress

## Problem statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **api server or etcd latency prevents drain progress**, using evidence from the deployed cluster rather than assuming every `Updating` pool is a drain failure.

## Trigger and scope
- Lifecycle stage: **API requests / eviction coordination**
- Trigger signal: Multiple unrelated drain operations show timeouts, `context deadline exceeded`, request throttling, API errors, or webhook failures that correlate with API instability.
- In scope: read-only evidence gathering, causal classification, confidence reporting, recommended next step, and recovery verification.
- Out of scope: autonomous disruptive changes, unsupported node mutation, or declaring an upgrade healthy based on one signal.

## Required evidence
ClusterOperator kube-apiserver/etcd conditions, API request errors, etcd alerts, latency metrics, controller logs across nodes, event write failures.

## Diagnostic commands
```bash
oc get co kube-apiserver etcd machine-config
```
```bash
oc describe co kube-apiserver
```
```bash
oc describe co etcd
```
```bash
oc get --raw='/readyz?verbose'
```
```bash
oc get events -A --sort-by=.lastTimestamp
```
```bash
oc -n openshift-machine-config-operator logs <controller-pod> -c machine-config-controller --since=30m
```

## Remediation guidance
Treat as a control-plane incident. Follow API-server/etcd runbooks, restore control-plane health, then re-evaluate the drain. Avoid changing PDBs or deleting pods when API failures are broad and the specific blocker is not established.

## Safety constraints
Control-plane remediation is high impact. Do not restart control-plane components or alter etcd membership based only on drain symptoms.
- Never fabricate output or infer a cause from MCP status alone.
- Record cluster version, timestamp, affected node, MCP, relevant namespace/pod and exact error.
- If API connectivity or evidence is insufficient, stop and report the missing data rather than recommending destructive cleanup.
- Mutation requires explicit human approval, change record, bounded scope, rollback plan and post-change validation.

## Success criteria
API readiness and latency recover, requests succeed consistently, and the same drain request progresses without broad timeouts.

## Acceptance tests
1. Given the trigger signal and supporting evidence, the agent identifies this use case or explicitly reports ambiguity.
2. The agent returns evidence references and distinguishes observed facts from hypotheses.
3. The agent recommends read-only checks before any mutation.
4. The agent does not execute a high-risk action without approval.
5. The agent verifies the stated success criteria after remediation.


## Kubernetes object observability requirements

**Scenario:** API server or etcd latency

The agent can query only Splunk MCP and Prometheus MCP. The object evidence below must be emitted by the separate read-only object/Event collector into Splunk; do not assume direct Kubernetes API access from the agent. Existing container logs and Prometheus metrics remain complementary evidence.

### Required object evidence
- Event (API-related object errors where recorded; event time and involved object)
- Node and Lease snapshots only when node heartbeats are affected
- MCP/Node state for stalled rollout context
- ClusterOperator conditions and ClusterVersion status when available and relevant

### Correlation rule
Logs and Prometheus are primary. Use object snapshots only to show correlated symptoms such as delayed node conditions, stale leases or rollout stagnation. Object state alone cannot establish API/etcd latency.

### Diagnosis gate
Require latency/error metrics or explicit API-server/etcd logs. A stale object, missing Event, or unchanged MCP status alone does not prove API/etcd latency.

### Missing-data behaviour
If the relevant object type, field, historical state, timestamp, or relationship is unavailable, record the exact evidence gap. Do not infer a negative result from a missing record or failed query. Downgrade the finding to `probable` or `inconclusive` as appropriate.

## Agent graph integration contract (shared)

This use case is invoked by the shared 12-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`. It must not create a separate autonomous agent. Its `skill.md` defines classification signals, required evidence, discriminating follow-up queries, diagnosis gates, stop conditions and safe recommendations.

### Required runtime fields
- `cluster_id`, `cluster_name`, `openshift_version`, `node_name` (when applicable), `lifecycle_stage`, `use_case_id`, `skill_version`, `started_at`, `deadline_at`.
- Evidence records include source/tool, cluster/resource identity, query/request reference, event/observed/ingested timestamps, freshness, redaction state and content hash.
- Every hypothesis must cite evidence IDs and list contradictions or missing facts.

### Bounded execution
- Max 3 evidence rounds; max 8 total tool calls; 15-second per-call timeout; at most 2 retries for transient errors only; overall interactive deadline 90 seconds. These are agent configuration defaults, not OpenShift/MCO product timeouts.
- Stop as `inconclusive` when minimum evidence is missing, identity is ambiguous, tools fail, or contradictory evidence cannot be resolved within budget. Tool failure must never be reported as absence of a fault.

### Safety and persistence
- Read-only Splunk MCP and Prometheus MCP access only for the agent; the separate collector has narrowly scoped read-only Kubernetes access. No mutation, exec, secret reads, force deletion, patching, reboot, storage detach, VM change, MCP change, or remediation execution.
- Persist incident summary and evidence metadata to PostgreSQL using `db/migrations/001_initial.sql`; keep raw telemetry in its source system. SQL retrieval first; pgvector is deferred. Historical cases prioritize checks but do not prove current root cause.
- Verify the deployed OpenShift version and use release-matched runbooks/source. If compatibility is unverified, say so explicitly.

## Case-specific diagnosis gate

**API/etcd latency:** Use apiserver/etcd latency, errors, saturation and control-plane logs around the drain window. Avoid attributing a single timeout to etcd without corroboration.

Acceptance criteria: (1) correct cluster and lifecycle scope are validated; (2) diagnosis references time-bounded evidence IDs; (3) missing or stale data yields an explicit unknown/inconclusive outcome; (4) no mutation tool is called; (5) the report distinguishes observed facts, hypotheses, contradictions and recommendations.
