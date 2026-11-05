# SPEC: Pod remains Terminating or finalizer cleanup stalls

## Problem statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **pod remains terminating or finalizer cleanup stalls**, using evidence from the deployed cluster rather than assuming every `Updating` pool is a drain failure.

## Trigger and scope
- Lifecycle stage: **Pod deletion / termination**
- Trigger signal: MCC reports `error when waiting for pod ... to terminate` and repeats after the drain-helper timeout; pod has a persistent deletionTimestamp.
- In scope: read-only evidence gathering, causal classification, confidence reporting, recommended next step, and recovery verification.
- Out of scope: autonomous disruptive changes, unsupported node mutation, or declaring an upgrade healthy based on one signal.

## Required evidence
Pod deletionTimestamp, grace period, container states, finalizers, owner references, events, node Ready condition, kubelet/CRI-O logs where available.

## Diagnostic commands
```bash
oc get pod <pod> -n <namespace> -o yaml
```
```bash
oc describe pod <pod> -n <namespace>
```
```bash
oc get pod <pod> -n <namespace> -o jsonpath='{.metadata.deletionTimestamp}{"\n"}{.metadata.finalizers}{"\n"}{.spec.terminationGracePeriodSeconds}{"\n"}'
```
```bash
oc describe node <node>
```
```bash
oc get events -A --sort-by=.lastTimestamp
```

## Remediation guidance
Identify whether the blocker is application shutdown, a finalizer controller, kubelet, or CRI-O. Repair the owning controller or node/runtime issue. Remove a finalizer only after proving its cleanup obligation is complete or explicitly accepting the consequence through an approved incident decision.

## Safety constraints
Nulling finalizers or force-deleting a pod can orphan external resources or bypass graceful shutdown; it is not a generic drain fix.
- Never fabricate output or infer a cause from MCP status alone.
- Record cluster version, timestamp, affected node, MCP, relevant namespace/pod and exact error.
- If API connectivity or evidence is insufficient, stop and report the missing data rather than recommending destructive cleanup.
- Mutation requires explicit human approval, change record, bounded scope, rollback plan and post-change validation.

## Success criteria
Pod termination completes normally or an approved, documented exception resolves the finalizer safely; the drain is retried and the node lifecycle advances.

## Acceptance tests
1. Given the trigger signal and supporting evidence, the agent identifies this use case or explicitly reports ambiguity.
2. The agent returns evidence references and distinguishes observed facts from hypotheses.
3. The agent recommends read-only checks before any mutation.
4. The agent does not execute a high-risk action without approval.
5. The agent verifies the stated success criteria after remediation.


## Kubernetes object observability requirements

**Scenario:** Pod termination or finalizer stall

The agent can query only Splunk MCP and Prometheus MCP. The object evidence below must be emitted by the separate read-only object/Event collector into Splunk; do not assume direct Kubernetes API access from the agent. Existing container logs and Prometheus metrics remain complementary evidence.

### Required object evidence
- Pod (UID, nodeName, deletionTimestamp, finalizers, phase, conditions, container states)
- Event (FailedKillPod, killing, termination or finalizer-related reason/message where present)
- Owning Deployment/ReplicaSet/StatefulSet/DaemonSet (ownerReferences, selector, replica status)
- PVC/PV/VolumeAttachment when volume cleanup is implicated
- Node (readiness and pressure conditions)

### Correlation rule
Use the Pod UID and deletion timestamp to establish how long termination has been pending; correlate kubelet/runtime and controller logs, events, finalizer owners, and storage relationships.

### Diagnosis gate
Do not recommend removing a finalizer solely because it exists. Confirm the specific cleanup controller or dependency is stalled using logs/events and object state; otherwise mark the cause probable/inconclusive.

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

**Pod termination/finalizer:** Confirm pod deletionTimestamp, finalizers, owner, node reachability and relevant controller events. Never clear finalizers automatically.

Acceptance criteria: (1) correct cluster and lifecycle scope are validated; (2) diagnosis references time-bounded evidence IDs; (3) missing or stale data yields an explicit unknown/inconclusive outcome; (4) no mutation tool is called; (5) the report distinguishes observed facts, hypotheses, contradictions and recommendations.
