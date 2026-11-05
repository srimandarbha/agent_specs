# SPEC: OS pivot, reboot or post-reboot verification fails

## Problem statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **os pivot, reboot or post-reboot verification fails**, using evidence from the deployed cluster rather than assuming every `Updating` pool is a drain failure.

## Trigger and scope
- Lifecycle stage: **Apply / OS pivot / reboot**
- Trigger signal: Drain has completed but node does not return Ready or update completion; MCD logs mention rpm-ostree, pivot, booted OS image, reboot or current/desired config verification.
- In scope: read-only evidence gathering, causal classification, confidence reporting, recommended next step, and recovery verification.
- Out of scope: autonomous disruptive changes, unsupported node mutation, or declaring an upgrade healthy based on one signal.

## Required evidence
MCD logs before and after reboot, node Ready/lease, boot ID, pivot/rpm-ostree logs, machine console, current/desired config and ClusterVersion status.

## Diagnostic commands
```bash
oc get mcp <pool> -o yaml
```
```bash
oc describe node <node>
```
```bash
oc -n openshift-machine-config-operator get pods -o wide | grep <node>
```
```bash
oc -n openshift-machine-config-operator logs <mcd-pod> -c machine-config-daemon --since=2h
```
```bash
oc get clusterversion
```
```bash
oc get co machine-config
```

## Remediation guidance
Use node console and release-specific OS upgrade recovery guidance. Confirm image/payload availability and booted deployment, then restore node health using the supported recovery path. Do not repeatedly reboot without examining boot/pivot evidence.

## Safety constraints
OS rollback, node replacement, or force-reapply can affect availability and should follow the documented recovery procedure with workload and platform owners engaged.
- Never fabricate output or infer a cause from MCP status alone.
- Record cluster version, timestamp, affected node, MCP, relevant namespace/pod and exact error.
- If API connectivity or evidence is insufficient, stop and report the missing data rather than recommending destructive cleanup.
- Mutation requires explicit human approval, change record, bounded scope, rollback plan and post-change validation.

## Success criteria
Node boots into the expected OS/config, becomes Ready, MCD verification passes, and the pool's updated count advances.

## Acceptance tests
1. Given the trigger signal and supporting evidence, the agent identifies this use case or explicitly reports ambiguity.
2. The agent returns evidence references and distinguishes observed facts from hypotheses.
3. The agent recommends read-only checks before any mutation.
4. The agent does not execute a high-risk action without approval.
5. The agent verifies the stated success criteria after remediation.


## Kubernetes object observability requirements

**Scenario:** OS pivot, reboot or post-reboot verification failure

The agent can query only Splunk MCP and Prometheus MCP. The object evidence below must be emitted by the separate read-only object/Event collector into Splunk; do not assume direct Kubernetes API access from the agent. Existing container logs and Prometheus metrics remain complementary evidence.

### Required object evidence
- Node (conditions, transition times, current/desired config and state/reason annotations when present)
- MachineConfigPool (conditions and rollout counters)
- MachineConfig (desired configuration identity)
- Event (node readiness and configuration lifecycle events)
- Lease (heartbeat timing when reboot/return-to-service is in question)

### Correlation rule
Use MCD/MCC logs and Prometheus as primary evidence; correlate reboot/pivot timestamps with Node conditions, Lease renewals, config annotations and MCP counters.

### Diagnosis gate
A temporary missing heartbeat can be expected during reboot. Diagnose failure only when the expected return/verification window is exceeded and corroborating logs or sustained state support it.

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

**OS pivot/reboot failure:** Correlate pivot/service logs, node availability, boot ID if exposed, current config and post-reboot MCD state. Do not initiate a reboot.

Acceptance criteria: (1) correct cluster and lifecycle scope are validated; (2) diagnosis references time-bounded evidence IDs; (3) missing or stale data yields an explicit unknown/inconclusive outcome; (4) no mutation tool is called; (5) the report distinguishes observed facts, hypotheses, contradictions and recommendations.
