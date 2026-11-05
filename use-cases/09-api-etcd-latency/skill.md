# Skill: Diagnose API server or etcd latency prevents drain progress

## Purpose
Use this skill when an MCP or cluster upgrade may be blocked by **api server or etcd latency prevents drain progress**.

## Required inputs
- Cluster/OpenShift version and incident time window.
- MCP name and affected node, if known.
- Exact MCO/MCD log line or alert.
- Access to Splunk MCP object snapshots/events from the separate collector and relevant operator logs; Prometheus MCP for metrics. The agent has no direct Kubernetes API tool.

## Procedure
1. Start with the MCC log. Identify the exact node and the exact pod or operation named in the error.
2. Confirm the current lifecycle stage. Do not call it a drain issue if the drain has completed and the failure is in apply/reboot/uncordon.
3. Run the following read-only checks:
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
4. Compare observations against the expected signal: Multiple unrelated drain operations show timeouts, `context deadline exceeded`, request throttling, API errors, or webhook failures that correlate with API instability.
5. Validate the primary cause using these evidence sources: ClusterOperator kube-apiserver/etcd conditions, API request errors, etcd alerts, latency metrics, controller logs across nodes, event write failures.
6. Consider alternative causes, including broad API/etcd issues and node health, before concluding.
7. Recommend the narrowest supported fix: Treat as a control-plane incident. Follow API-server/etcd runbooks, restore control-plane health, then re-evaluate the drain. Avoid changing PDBs or deleting pods when API failures are broad and the specific blocker is not established.
8. Explain the operational risk: Control-plane remediation is high impact. Do not restart control-plane components or alter etcd membership based only on drain symptoms.
9. Define verification using: API readiness and latency recover, requests succeed consistently, and the same drain request progresses without broad timeouts.
10. If evidence is incomplete, report what is missing and escalate. Do not guess.

## Output format
Return:
- **Classification:** confirmed / likely / inconclusive
- **Lifecycle stage:**
- **Affected objects:**
- **Observed evidence:** timestamped excerpts and resource references
- **Root-cause reasoning:** evidence for and against
- **Recommended next action:** read-only first
- **Risk and approval:** explicit
- **Verification:** exact checks and expected state
- **Escalation trigger:** what would make the agent stop

## Prohibited autonomous actions
Do not force-delete pods, null finalizers, weaken PDBs, remove webhooks, detach volumes, change VM eviction policy, uncordon nodes, edit MCO coordination annotations, unpause MCPs, alter maxUnavailable, reboot/delete nodes or change host files. These require a human-approved, release-appropriate runbook and explicit confirmation.


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

## Executable skill contract

### Goal
Diagnose: **API/etcd latency**. Use apiserver/etcd latency, errors, saturation and control-plane logs around the drain window. Avoid attributing a single timeout to etcd without corroboration.

### Required evidence checklist
- [ ] Correct cluster, OpenShift version and target resource identity.
- [ ] Time-correlated controller/MCO logs from Splunk MCP.
- [ ] Relevant Prometheus signals when the hypothesis needs metrics.
- [ ] Read-only Kubernetes object state and events when applicable.
- [ ] Evidence freshness, source reference and contradictions recorded.

### Decision and stop rules
- `supported`: the case-specific required evidence is present and corroborated.
- `probable`: some evidence supports the hypothesis, but a required corroborating source is unavailable.
- `not_supported`: reliable evidence contradicts the hypothesis.
- `inconclusive`: identity, freshness, minimum evidence or tool availability is insufficient.
- Never treat missing telemetry as a zero value or failed query as a negative result. Stop after the shared graph budget is reached.

### Allowed actions
Read-only searches and object reads only. Recommend human-reviewed next steps; do not execute remediation. Do not expose secrets or persist full raw logs.
