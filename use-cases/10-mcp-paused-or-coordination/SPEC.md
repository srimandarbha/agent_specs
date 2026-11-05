# SPEC: MCP paused or rollout coordination prevents progress

## Problem statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **mcp paused or rollout coordination prevents progress**, using evidence from the deployed cluster rather than assuming every `Updating` pool is a drain failure.

## Trigger and scope
- Lifecycle stage: **MCP rollout coordination**
- Trigger signal: Pool reports paused, desired/current config mismatch persists, or rollout does not begin even though no active drain error is logged.
- In scope: read-only evidence gathering, causal classification, confidence reporting, recommended next step, and recovery verification.
- Out of scope: autonomous disruptive changes, unsupported node mutation, or declaring an upgrade healthy based on one signal.

## Required evidence
MCP spec/status, pause field, node selectors and labels, desired/current rendered config, unavailable counts, ClusterOperator conditions.

## Diagnostic commands
```bash
oc get mcp
```
```bash
oc get mcp <pool> -o yaml
```
```bash
oc describe mcp <pool>
```
```bash
oc get nodes --show-labels
```
```bash
oc get co machine-config
```
```bash
oc get clusterversion
```

## Remediation guidance
Confirm the pause and maintenance intent with the pool owner. If paused intentionally, resolve the scheduling/maintenance plan and get approval before unpausing; unpausing can apply all queued configuration, not just the change being investigated. Validate selectors and availability limits before modifying them.

## Safety constraints
Unpausing can trigger a broad rollout; changing maxUnavailable can disrupt more nodes than expected. Never unpause or raise disruption limits without approval.
- Never fabricate output or infer a cause from MCP status alone.
- Record cluster version, timestamp, affected node, MCP, relevant namespace/pod and exact error.
- If API connectivity or evidence is insufficient, stop and report the missing data rather than recommending destructive cleanup.
- Mutation requires explicit human approval, change record, bounded scope, rollback plan and post-change validation.

## Success criteria
Pool is intentionally unpaused or correctly configured, desired rollout begins, and node availability stays within the approved limit.

## Acceptance tests
1. Given the trigger signal and supporting evidence, the agent identifies this use case or explicitly reports ambiguity.
2. The agent returns evidence references and distinguishes observed facts from hypotheses.
3. The agent recommends read-only checks before any mutation.
4. The agent does not execute a high-risk action without approval.
5. The agent verifies the stated success criteria after remediation.


## Kubernetes object observability requirements

**Scenario:** MCP paused or rollout coordination

The agent can query only Splunk MCP and Prometheus MCP. The object evidence below must be emitted by the separate read-only object/Event collector into Splunk; do not assume direct Kubernetes API access from the agent. Existing container logs and Prometheus metrics remain complementary evidence.

### Required object evidence
- MachineConfigPool (spec.paused, maxUnavailable, configuration, conditions, machine/updated/ready/unavailable counts)
- Node (currentConfig, desiredConfig, state/reason and drain coordination annotations when present; conditions; unschedulable)
- MachineConfig (desired configuration identity)
- Event (MCP/node rollout-related events)
- ClusterOperator/ClusterVersion status if rollout gate requires broader context

### Correlation rule
Correlate MCP pause/conditions and counters with target Node configuration annotations, MCC/MCD logs and drain timestamps. Verify exact annotation names against the deployed version.

### Diagnosis gate
Paused or Updating alone is not a drain-failure diagnosis. Require evidence that rollout coordination or node state prevents the specific lifecycle transition.

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

**MCP paused/coordination:** Read MCP spec/status, paused flag, maxUnavailable, node annotations and rollout status. Paused or updating state alone does not prove drain failure.

Acceptance criteria: (1) correct cluster and lifecycle scope are validated; (2) diagnosis references time-bounded evidence IDs; (3) missing or stale data yields an explicit unknown/inconclusive outcome; (4) no mutation tool is called; (5) the report distinguishes observed facts, hypotheses, contradictions and recommendations.
