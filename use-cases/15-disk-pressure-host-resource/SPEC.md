# SPEC: Node disk pressure or host resource exhaustion stalls cleanup/update

## Problem statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **node disk pressure or host resource exhaustion stalls cleanup/update**, using evidence from the deployed cluster rather than assuming every `Updating` pool is a drain failure.

## Trigger and scope
- Lifecycle stage: **Node runtime / storage / apply**
- Trigger signal: Node `DiskPressure`, filesystem or inode exhaustion, CRI-O image/container storage errors, kubelet errors, or MCD cannot write/apply configuration.
- In scope: read-only evidence gathering, causal classification, confidence reporting, recommended next step, and recovery verification.
- Out of scope: autonomous disruptive changes, unsupported node mutation, or declaring an upgrade healthy based on one signal.

## Required evidence
Node conditions/events, filesystem and inode metrics, kubelet/CRI-O logs, MCD write errors, node-exporter/monitoring data, host journal.

## Diagnostic commands
```bash
oc describe node <node>
```
```bash
oc get events -A --sort-by=.lastTimestamp
```
```bash
oc adm node-logs <node> --path=journal
```
```bash
oc -n openshift-machine-config-operator logs <mcd-pod> -c machine-config-daemon --since=2h
```
```bash
oc get co machine-config
```

## Remediation guidance
Identify the exhausted filesystem/resource and clean up only through the supported node/storage procedure. Confirm no critical data is removed and restore headroom before retrying the update.

## Safety constraints
Blind deletion under `/var/lib/containers`, `/var/lib/kubelet`, or managed OS paths can corrupt node state. Avoid ad-hoc host cleanup.
- Never fabricate output or infer a cause from MCP status alone.
- Record cluster version, timestamp, affected node, MCP, relevant namespace/pod and exact error.
- If API connectivity or evidence is insufficient, stop and report the missing data rather than recommending destructive cleanup.
- Mutation requires explicit human approval, change record, bounded scope, rollback plan and post-change validation.

## Success criteria
Node pressure clears, kubelet/CRI-O and MCD operate normally, and update progresses.

## Acceptance tests
1. Given the trigger signal and supporting evidence, the agent identifies this use case or explicitly reports ambiguity.
2. The agent returns evidence references and distinguishes observed facts from hypotheses.
3. The agent recommends read-only checks before any mutation.
4. The agent does not execute a high-risk action without approval.
5. The agent verifies the stated success criteria after remediation.


## Kubernetes object observability requirements

**Scenario:** Disk pressure or host resource exhaustion

The agent can query only Splunk MCP and Prometheus MCP. The object evidence below must be emitted by the separate read-only object/Event collector into Splunk; do not assume direct Kubernetes API access from the agent. Existing container logs and Prometheus metrics remain complementary evidence.

### Required object evidence
- Node (DiskPressure/MemoryPressure/PIDPressure, transition times, capacity/allocatable)
- Pod (nodeName, phase/conditions, resource requests/limits, ephemeral-storage requests/limits where configured, termination state)
- Event (eviction, image filesystem, ephemeral storage, node pressure events)
- PVC/PV only if storage capacity or mount pressure is implicated
- MCP/Node config state if resource exhaustion coincides with update lifecycle

### Correlation rule
Prometheus host/node metrics and node/kubelet/CRI-O logs are primary. Use Node conditions and events to correlate the resource-pressure state with drain and pod termination timeline.

### Diagnosis gate
Do not attribute DiskPressure to a particular Pod without supporting eviction/ephemeral-storage evidence. Distinguish node filesystem pressure from PVC/backend capacity issues.

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

**Disk pressure/resource exhaustion:** Correlate node conditions, filesystem/inode metrics, eviction signals and MCD/CRI-O logs. Do not delete files or prune runtime storage automatically.

Acceptance criteria: (1) correct cluster and lifecycle scope are validated; (2) diagnosis references time-bounded evidence IDs; (3) missing or stale data yields an explicit unknown/inconclusive outcome; (4) no mutation tool is called; (5) the report distinguishes observed facts, hypotheses, contradictions and recommendations.
