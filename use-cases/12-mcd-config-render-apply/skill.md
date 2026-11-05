# Skill: Diagnose Rendered MachineConfig or configuration application failure

## Purpose
Use this skill when an MCP or cluster upgrade may be blocked by **rendered machineconfig or configuration application failure**.

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
oc get mcp <pool> -o yaml
```
```bash
oc get mc
```
```bash
oc get mc <rendered-config> -o yaml
```
```bash
oc describe node <node>
```
```bash
oc -n openshift-machine-config-operator logs <controller-pod> -c machine-config-controller --since=2h
```
```bash
oc -n openshift-machine-config-operator logs <mcd-pod> -c machine-config-daemon --since=2h
```
4. Compare observations against the expected signal: MCP desired rendered config differs from current; MCO or MCD reports render, validation, unsupported config, file-write, systemd or update errors without a drain blocker.
5. Validate the primary cause using these evidence sources: MCP `status.configuration`, rendered MachineConfig existence, MachineConfig objects, MCO/MCD logs, node current/desired config annotations and degraded reason.
6. Consider alternative causes, including broad API/etcd issues and node health, before concluding.
7. Recommend the narrowest supported fix: Separate render-time failures from node apply failures. Validate the source MachineConfig and the rendered result; correct the owning config through GitOps/source-of-truth. For unsupported changes, use supported configuration APIs rather than patching rendered objects.
8. Explain the operational risk: Editing generated rendered MachineConfigs or making unmanaged host changes creates drift and is not a durable fix.
9. Define verification using: Valid desired rendered config exists, MCD applies it, node reports target config, and MCP progresses.
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

**Scenario:** Rendered MachineConfig or application failure

The agent can query only Splunk MCP and Prometheus MCP. The object evidence below must be emitted by the separate read-only object/Event collector into Splunk; do not assume direct Kubernetes API access from the agent. Existing container logs and Prometheus metrics remain complementary evidence.

### Required object evidence
- MachineConfigPool (desired configuration reference, conditions and rollout counters)
- MachineConfig (name, labels, configuration identity and relevant status/metadata)
- Node (currentConfig, desiredConfig, state/reason annotations when present)
- Event (MCP/node configuration application failures)

### Correlation rule
Correlate rendered config identity and MCP desired reference with MCD logs, node annotations and event times. Avoid exporting full configuration payloads unless specifically approved.

### Diagnosis gate
A missing or changing rendered config reference is not enough. Require explicit render/apply failure evidence and a consistent relationship among MCP, MachineConfig and target node.

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
Diagnose: **Rendered config/apply failure**. Compare desired/current rendered MachineConfig references and MCD error details; confirm release-specific behavior before interpretation.

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
