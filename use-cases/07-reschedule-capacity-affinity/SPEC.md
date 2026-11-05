# SPEC: Replacement workloads cannot schedule after eviction

## Problem statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **replacement workloads cannot schedule after eviction**, using evidence from the deployed cluster rather than assuming every `Updating` pool is a drain failure.

## Trigger and scope
- Lifecycle stage: **Post-eviction scheduling / rollout coordination**
- Trigger signal: Drain evicts pods, but replacement pods stay Pending; events cite insufficient CPU/memory, taints, affinity, topology, node selector or volume topology.
- In scope: read-only evidence gathering, causal classification, confidence reporting, recommended next step, and recovery verification.
- Out of scope: autonomous disruptive changes, unsupported node mutation, or declaring an upgrade healthy based on one signal.

## Required evidence
Pending pod events; requests/limits; node allocatable and pressure; affinity rules; taints; PVC topology; MCP maxUnavailable and number of ready nodes.

## Diagnostic commands
```bash
oc get pods -A --field-selector=status.phase=Pending -o wide
```
```bash
oc describe pod <pending-pod> -n <namespace>
```
```bash
oc get nodes
```
```bash
oc describe node <candidate-node>
```
```bash
oc get mcp <pool> -o yaml
```
```bash
oc get pdb -A
```

## Remediation guidance
Restore node capacity or correct the precise scheduling constraint. Consider workload-owner-approved affinity changes or additional capacity. Respect pool availability constraints and avoid draining another node until workload recovery is verified.

## Safety constraints
Relaxing required anti-affinity or topology rules may violate application resilience assumptions. Do not scale down additional nodes to make the update appear to progress.
- Never fabricate output or infer a cause from MCP status alone.
- Record cluster version, timestamp, affected node, MCP, relevant namespace/pod and exact error.
- If API connectivity or evidence is insufficient, stop and report the missing data rather than recommending destructive cleanup.
- Mutation requires explicit human approval, change record, bounded scope, rollback plan and post-change validation.

## Success criteria
Required replicas schedule and become Ready on eligible nodes; PDBs are healthy and MCP proceeds within the configured disruption budget.

## Acceptance tests
1. Given the trigger signal and supporting evidence, the agent identifies this use case or explicitly reports ambiguity.
2. The agent returns evidence references and distinguishes observed facts from hypotheses.
3. The agent recommends read-only checks before any mutation.
4. The agent does not execute a high-risk action without approval.
5. The agent verifies the stated success criteria after remediation.


## Kubernetes object observability requirements

**Scenario:** Replacement workload cannot schedule

The agent can query only Splunk MCP and Prometheus MCP. The object evidence below must be emitted by the separate read-only object/Event collector into Splunk; do not assume direct Kubernetes API access from the agent. Existing container logs and Prometheus metrics remain complementary evidence.

### Required object evidence
- Pod (nodeName, nodeSelector, affinity/anti-affinity, tolerations, resource requests/limits, ownerReferences, phase/conditions)
- Node (allocatable/capacity, taints, labels, readiness, pressure)
- Deployment/ReplicaSet/StatefulSet/DaemonSet (selector and desired/ready/available replicas)
- Event (FailedScheduling and scheduling reason/message)
- ResourceQuota (hard/used values when quota is suspected)
- PDB (context for disruption constraints)

### Correlation rule
Link the evicted Pod to its owner and replacement Pod(s); compare scheduling event reasons with node labels/taints/allocatable capacity, affinity rules and quota at the same time.

### Diagnosis gate
Do not diagnose capacity shortage from a Pending phase alone. Require scheduler event/reason or equivalent metrics and show which constraint is unsatisfied. Distinguish hard affinity from preferred affinity.

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

**Replacement scheduling failure:** Inspect Pending pod events, requests, node allocatable/taints, selectors, affinity/anti-affinity and topology constraints. Distinguish capacity from constraints.

Acceptance criteria: (1) correct cluster and lifecycle scope are validated; (2) diagnosis references time-bounded evidence IDs; (3) missing or stale data yields an explicit unknown/inconclusive outcome; (4) no mutation tool is called; (5) the report distinguishes observed facts, hypotheses, contradictions and recommendations.
