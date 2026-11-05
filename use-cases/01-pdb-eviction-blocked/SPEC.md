# SPEC: PodDisruptionBudget blocks eviction

## Problem statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **poddisruptionbudget blocks eviction**, using evidence from the deployed cluster rather than assuming every `Updating` pool is a drain failure.

## Trigger and scope
- Lifecycle stage: **Drain / eviction**
- Trigger signal: MCC log contains `Cannot evict pod as it would violate the pod's disruption budget` or equivalent eviction-subresource denial.
- In scope: read-only evidence gathering, causal classification, confidence reporting, recommended next step, and recovery verification.
- Out of scope: autonomous disruptive changes, unsupported node mutation, or declaring an upgrade healthy based on one signal.

## Required evidence
MCC drain log naming namespace/pod; `oc get pdb -A`; PDB `status.disruptionsAllowed`, `currentHealthy`, `desiredHealthy`; owning workload replica status; replacement scheduling events.

## Diagnostic commands
```bash
oc -n openshift-machine-config-operator logs <controller-pod> -c machine-config-controller --since=2h | grep -Ei 'drain|evict|disruption budget|<node>'
```
```bash
oc get pdb -A
```
```bash
oc describe pdb <pdb> -n <namespace>
```
```bash
oc get deploy,sts,rs -n <namespace> -o wide
```
```bash
oc get pods -n <namespace> -o wide
```

## Remediation guidance
Restore intended healthy replicas and scheduling capacity first. Confirm the PDB selector and whether more than one PDB selects the pod. If policy must be changed, use an approved temporary change, record the original manifest, scope the change narrowly, and restore/verify it after the node update.

## Safety constraints
Changing `minAvailable`/`maxUnavailable` weakens availability guarantees; never patch to zero without service-owner approval and a rollback record.
- Never fabricate output or infer a cause from MCP status alone.
- Record cluster version, timestamp, affected node, MCP, relevant namespace/pod and exact error.
- If API connectivity or evidence is insufficient, stop and report the missing data rather than recommending destructive cleanup.
- Mutation requires explicit human approval, change record, bounded scope, rollback plan and post-change validation.

## Success criteria
MCC logs show the blocker pod evicted/deleted, desired and last-applied drainer annotations converge, node update progresses, and original PDB policy is restored and verified.

## Acceptance tests
1. Given the trigger signal and supporting evidence, the agent identifies this use case or explicitly reports ambiguity.
2. The agent returns evidence references and distinguishes observed facts from hypotheses.
3. The agent recommends read-only checks before any mutation.
4. The agent does not execute a high-risk action without approval.
5. The agent verifies the stated success criteria after remediation.


## Kubernetes object observability requirements

**Scenario:** PDB blocks eviction

The agent can query only Splunk MCP and Prometheus MCP. The object evidence below must be emitted by the separate read-only object/Event collector into Splunk; do not assume direct Kubernetes API access from the agent. Existing container logs and Prometheus metrics remain complementary evidence.

### Required object evidence
- Pod (namespace/name/UID, labels, nodeName, ownerReferences, deletionTimestamp, finalizers, readiness/phase)
- PodDisruptionBudget (selector, minAvailable/maxUnavailable, currentHealthy, desiredHealthy, expectedPods, disruptionsAllowed, disruptedPods, observedGeneration)
- Event (eviction denial reason/message, involved object, event time)
- Owning Deployment/ReplicaSet/StatefulSet and replica health
- Node (name, readiness, schedulability)

### Correlation rule
Join the MCC eviction-denial log to the exact Pod by cluster, namespace, name/UID and time; evaluate PDB selector semantics in the same namespace against captured Pod labels; compare timestamped PDB status with the eviction time.

### Diagnosis gate
Confirmed only when a specific eviction denial is correlated with the target Pod and a matching PDB state at the relevant time. `disruptionsAllowed=0` alone is insufficient. If historical PDB state or selector inputs are missing, report probable/inconclusive.

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

**PDB/eviction blocked:** Require a matching target pod, namespace/selector match, PDB status and time-correlated eviction/drain failure. disruptionsAllowed=0 alone is not proof that this specific drain is blocked.

Acceptance criteria: (1) correct cluster and lifecycle scope are validated; (2) diagnosis references time-bounded evidence IDs; (3) missing or stale data yields an explicit unknown/inconclusive outcome; (4) no mutation tool is called; (5) the report distinguishes observed facts, hypotheses, contradictions and recommendations.
