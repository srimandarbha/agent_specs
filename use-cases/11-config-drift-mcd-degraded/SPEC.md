# SPEC: Machine Config Daemon reports configuration drift

## Problem statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **machine config daemon reports configuration drift**, using evidence from the deployed cluster rather than assuming every `Updating` pool is a drain failure.

## Trigger and scope
- Lifecycle stage: **MCD preflight / configuration apply**
- Trigger signal: Node/MCP degraded with on-disk state mismatch or config drift messages; node may still be Ready but refuses update.
- In scope: read-only evidence gathering, causal classification, confidence reporting, recommended next step, and recovery verification.
- Out of scope: autonomous disruptive changes, unsupported node mutation, or declaring an upgrade healthy based on one signal.

## Required evidence
MCD logs, node annotations/conditions, current and desired rendered MachineConfig, event showing drifted path, host file metadata/content under approved access.

## Diagnostic commands
```bash
oc describe node <node>
```
```bash
oc get mcp <pool> -o yaml
```
```bash
oc -n openshift-machine-config-operator get pods -o wide | grep <node>
```
```bash
oc -n openshift-machine-config-operator logs <mcd-pod> -c machine-config-daemon --since=2h
```
```bash
oc get events -A --sort-by=.lastTimestamp
```

## Remediation guidance
Identify the exact drifted object and authoritative desired content. Restore the managed file/permissions to match the applied config, or follow the release-specific MCO recovery procedure. Force-reapply mechanisms may reboot the node and require explicit approval.

## Safety constraints
Do not manually edit managed host files or create an MCD forcefile as a casual workaround; either can trigger unexpected changes/reboot.
- Never fabricate output or infer a cause from MCP status alone.
- Record cluster version, timestamp, affected node, MCP, relevant namespace/pod and exact error.
- If API connectivity or evidence is insufficient, stop and report the missing data rather than recommending destructive cleanup.
- Mutation requires explicit human approval, change record, bounded scope, rollback plan and post-change validation.

## Success criteria
MCD preflight passes, node state is no longer Degraded, and the target config is applied and verified.

## Acceptance tests
1. Given the trigger signal and supporting evidence, the agent identifies this use case or explicitly reports ambiguity.
2. The agent returns evidence references and distinguishes observed facts from hypotheses.
3. The agent recommends read-only checks before any mutation.
4. The agent does not execute a high-risk action without approval.
5. The agent verifies the stated success criteria after remediation.


## Kubernetes object observability requirements

**Scenario:** Configuration drift or MCD degraded

The agent can query only Splunk MCP and Prometheus MCP. The object evidence below must be emitted by the separate read-only object/Event collector into Splunk; do not assume direct Kubernetes API access from the agent. Existing container logs and Prometheus metrics remain complementary evidence.

### Required object evidence
- Node (currentConfig, desiredConfig, state, reason annotations when present; conditions and transition times)
- MachineConfigPool (configuration, conditions, counts)
- MachineConfig (name/labels and configuration identity; limit payload collection)
- Event (node/MCP condition changes)

### Correlation rule
Match MCD logs and drift/degraded messages to the same node and time; compare node current/desired config identifiers to the MCP desired configuration and available MachineConfig metadata.

### Diagnosis gate
Do not infer drift merely because current and desired config differ during a normal rollout. Require MCD drift/degraded evidence or a sustained mismatch outside expected progression.

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

**Config drift/MCD degraded:** Correlate MCD state/reason, node annotations and daemon logs with current rendered config. Distinguish drift from a transient update stage.

Acceptance criteria: (1) correct cluster and lifecycle scope are validated; (2) diagnosis references time-bounded evidence IDs; (3) missing or stale data yields an explicit unknown/inconclusive outcome; (4) no mutation tool is called; (5) the report distinguishes observed facts, hypotheses, contradictions and recommendations.
