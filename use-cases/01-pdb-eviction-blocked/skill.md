# Skill: Diagnose PodDisruptionBudget blocks eviction

## Purpose
Use this skill when an MCP or cluster upgrade may be blocked by **poddisruptionbudget blocks eviction**.

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
4. Compare observations against the expected signal: MCC log contains `Cannot evict pod as it would violate the pod's disruption budget` or equivalent eviction-subresource denial.
5. Validate the primary cause using these evidence sources: MCC drain log naming namespace/pod; `oc get pdb -A`; PDB `status.disruptionsAllowed`, `currentHealthy`, `desiredHealthy`; owning workload replica status; replacement scheduling events.
6. Consider alternative causes, including broad API/etcd issues and node health, before concluding.
7. Recommend the narrowest supported fix: Restore intended healthy replicas and scheduling capacity first. Confirm the PDB selector and whether more than one PDB selects the pod. If policy must be changed, use an approved temporary change, record the original manifest, scope the change narrowly, and restore/verify it after the node update.
8. Explain the operational risk: Changing `minAvailable`/`maxUnavailable` weakens availability guarantees; never patch to zero without service-owner approval and a rollback record.
9. Define verification using: MCC logs show the blocker pod evicted/deleted, desired and last-applied drainer annotations converge, node update progresses, and original PDB policy is restored and verified.
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

## Executable skill contract

### Goal
Diagnose: **PDB/eviction blocked**. Require a matching target pod, namespace/selector match, PDB status and time-correlated eviction/drain failure. disruptionsAllowed=0 alone is not proof that this specific drain is blocked.

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
