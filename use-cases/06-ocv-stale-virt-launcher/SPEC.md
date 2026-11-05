# SPEC: Stale source virt-launcher pod after completed migration

## Problem statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **stale source virt-launcher pod after completed migration**, using evidence from the deployed cluster rather than assuming every `Updating` pool is a drain failure.

## Trigger and scope
- Lifecycle stage: **OCV pod cleanup / drain**
- Trigger signal: Drain repeatedly times out on an old `virt-launcher` pod even though the VM is Running elsewhere and VMIM objects show Succeeded; old source pod remains NotReady or partially ready.
- In scope: read-only evidence gathering, causal classification, confidence reporting, recommended next step, and recovery verification.
- Out of scope: autonomous disruptive changes, unsupported node mutation, or declaring an upgrade healthy based on one signal.

## Required evidence
VM current node, old launcher node and readiness, VMIM history, pod deletionTimestamp, container state, events, node health and virtualization operator version.

## Diagnostic commands
```bash
oc get vmi <vmi> -n <namespace> -o wide
```
```bash
oc get vmim -n <namespace> -o wide
```
```bash
oc get pods -n <namespace> -o wide | grep virt-launcher
```
```bash
oc get pod <old-virt-launcher> -n <namespace> -o yaml
```
```bash
oc describe pod <old-virt-launcher> -n <namespace>
```
```bash
oc describe node <old-node>
```

## Remediation guidance
Confirm VMIM completion and that the active VMI is healthy on its current node. Capture relevant pod/VMI/VMIM YAML and virtualization logs, then follow the matching Red Hat solution or support guidance for the deployed version. Resolve the stale pod/node cleanup cause before considering deletion.

## Safety constraints
Never delete a launcher solely because it looks old; prove it is not the active VM process and follow supported cleanup guidance. This case has a documented Red Hat solution: https://access.redhat.com/solutions/7146943.
- Never fabricate output or infer a cause from MCP status alone.
- Record cluster version, timestamp, affected node, MCP, relevant namespace/pod and exact error.
- If API connectivity or evidence is insufficient, stop and report the missing data rather than recommending destructive cleanup.
- Mutation requires explicit human approval, change record, bounded scope, rollback plan and post-change validation.

## Success criteria
Stale source pod is cleaned up using supported procedure, active VM remains healthy, and drain proceeds.

## Acceptance tests
1. Given the trigger signal and supporting evidence, the agent identifies this use case or explicitly reports ambiguity.
2. The agent returns evidence references and distinguishes observed facts from hypotheses.
3. The agent recommends read-only checks before any mutation.
4. The agent does not execute a high-risk action without approval.
5. The agent verifies the stated success criteria after remediation.


## Kubernetes object observability requirements

**Scenario:** Stale virt-launcher after completed migration

The agent can query only Splunk MCP and Prometheus MCP. The object evidence below must be emitted by the separate read-only object/Event collector into Splunk; do not assume direct Kubernetes API access from the agent. Existing container logs and Prometheus metrics remain complementary evidence.

### Required object evidence
- Pod (virt-launcher namespace/name/UID, nodeName, deletionTimestamp, phase, owner references)
- VirtualMachineInstance (current node assignment, phase/conditions, launcher Pod reference)
- VirtualMachineInstanceMigration (source/target nodes, phase, completion time, VMI reference)
- Event (Pod/VMI/migration events)
- Node (source and target readiness/schedulability)

### Correlation rule
Compare migration completion time and target VMI node with the source launcher Pod identity and node. Correlate virt-handler, migration-controller and kubelet logs before classifying a Pod as stale.

### Diagnosis gate
A launcher Pod remaining visible is not sufficient. Confirm the migration completed, the VMI is healthy on the target, and the old Pod is no longer the valid launcher before recommending human-reviewed cleanup.

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

**Stale virt-launcher after migration:** Verify migration object completion, source/destination VMI ownership, pod UID/node and timestamps before classifying a pod as stale. Never delete based only on age.

Acceptance criteria: (1) correct cluster and lifecycle scope are validated; (2) diagnosis references time-bounded evidence IDs; (3) missing or stale data yields an explicit unknown/inconclusive outcome; (4) no mutation tool is called; (5) the report distinguishes observed facts, hypotheses, contradictions and recommendations.
