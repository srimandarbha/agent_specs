# SPEC: Drain completion annotation or uncordon coordination mismatch

## Problem statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **drain completion annotation or uncordon coordination mismatch**, using evidence from the deployed cluster rather than assuming every `Updating` pool is a drain failure.

## Trigger and scope
- Lifecycle stage: **Drain controller coordination / uncordon**
- Trigger signal: Node remains cordoned or update does not advance despite pods appearing drained; desired-drainer and last-applied-drainer annotations differ, or an external actor uncordoned the node during drain.
- In scope: read-only evidence gathering, causal classification, confidence reporting, recommended next step, and recovery verification.
- Out of scope: autonomous disruptive changes, unsupported node mutation, or declaring an upgrade healthy based on one signal.

## Required evidence
Desired/last-applied drainer annotations, `spec.unschedulable`, MCC logs, MachineConfigNode conditions if available, API patch errors and events.

## Diagnostic commands
```bash
oc get node <node> -o jsonpath='{.spec.unschedulable}{"\n"}{.metadata.annotations.machineconfiguration\.openshift\.io/desiredDrain}{"\n"}{.metadata.annotations.machineconfiguration\.openshift\.io/lastAppliedDrain}{"\n"}'
```
```bash
oc describe node <node>
```
```bash
oc -n openshift-machine-config-operator logs <controller-pod> -c machine-config-controller --since=2h | grep -E '<node>|cordon|uncordon|annotation|drain'
```
```bash
oc get mcp <pool> -o yaml
```

## Remediation guidance
Use the actual annotation keys present in the deployed release; compare desired and last-applied values and find the controller/API error. Remove competing automation that toggles schedulability, then allow the MCO controller to reconcile. Do not manually forge completion annotations.

## Safety constraints
Manually editing drainer annotations or uncordoning during an active update can falsely signal completion while new pods are scheduled onto the node.
- Never fabricate output or infer a cause from MCP status alone.
- Record cluster version, timestamp, affected node, MCP, relevant namespace/pod and exact error.
- If API connectivity or evidence is insufficient, stop and report the missing data rather than recommending destructive cleanup.
- Mutation requires explicit human approval, change record, bounded scope, rollback plan and post-change validation.

## Success criteria
MCO-managed drain/uncordon request completes, coordination annotations converge through the controller, node schedulability matches the expected lifecycle phase, and MCP advances.

## Acceptance tests
1. Given the trigger signal and supporting evidence, the agent identifies this use case or explicitly reports ambiguity.
2. The agent returns evidence references and distinguishes observed facts from hypotheses.
3. The agent recommends read-only checks before any mutation.
4. The agent does not execute a high-risk action without approval.
5. The agent verifies the stated success criteria after remediation.


## Kubernetes object observability requirements

**Scenario:** Uncordon or drainer annotation coordination

The agent can query only Splunk MCP and Prometheus MCP. The object evidence below must be emitted by the separate read-only object/Event collector into Splunk; do not assume direct Kubernetes API access from the agent. Existing container logs and Prometheus metrics remain complementary evidence.

### Required object evidence
- Node (spec.unschedulable, desiredDrain/lastAppliedDrain and related MCO annotations when present, resourceVersion)
- Pod (nodeName and creation time for evidence of workloads scheduled during coordination race)
- Event (node scheduling/cordon/uncordon events when available)
- MCP (rollout state and counters)

### Correlation rule
Correlate Node schedulability and drain annotations with MCC logs and Pod scheduling timestamps. Preserve exact annotation values and observed times; verify names against the deployed release.

### Diagnosis gate
Do not edit annotations or uncordon automatically. Confirm a coordination mismatch from controller logs plus object-state history; a single current Node snapshot may miss the race.

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

**Uncordon/drainer coordination:** Read unschedulable state and exact drain coordination annotations. Treat unexpected uncordon as a safety signal; do not modify annotations or mark completion.

Acceptance criteria: (1) correct cluster and lifecycle scope are validated; (2) diagnosis references time-bounded evidence IDs; (3) missing or stale data yields an explicit unknown/inconclusive outcome; (4) no mutation tool is called; (5) the report distinguishes observed facts, hypotheses, contradictions and recommendations.
