# Skill: Diagnose Drain completion annotation or uncordon coordination mismatch

## Purpose
Use this skill when an MCP or cluster upgrade may be blocked by **drain completion annotation or uncordon coordination mismatch**.

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
4. Compare observations against the expected signal: Node remains cordoned or update does not advance despite pods appearing drained; desired-drainer and last-applied-drainer annotations differ, or an external actor uncordoned the node during drain.
5. Validate the primary cause using these evidence sources: Desired/last-applied drainer annotations, `spec.unschedulable`, MCC logs, MachineConfigNode conditions if available, API patch errors and events.
6. Consider alternative causes, including broad API/etcd issues and node health, before concluding.
7. Recommend the narrowest supported fix: Use the actual annotation keys present in the deployed release; compare desired and last-applied values and find the controller/API error. Remove competing automation that toggles schedulability, then allow the MCO controller to reconcile. Do not manually forge completion annotations.
8. Explain the operational risk: Manually editing drainer annotations or uncordoning during an active update can falsely signal completion while new pods are scheduled onto the node.
9. Define verification using: MCO-managed drain/uncordon request completes, coordination annotations converge through the controller, node schedulability matches the expected lifecycle phase, and MCP advances.
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

## Executable skill contract

### Goal
Diagnose: **Uncordon/drainer coordination**. Read unschedulable state and exact drain coordination annotations. Treat unexpected uncordon as a safety signal; do not modify annotations or mark completion.

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
