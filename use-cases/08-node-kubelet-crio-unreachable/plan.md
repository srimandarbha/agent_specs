# Implementation plan: Node becomes NotReady or kubelet/CRI-O cannot finish drain

## Phase 0: Ground truth
- [ ] Pin the supported OpenShift release(s) and obtain the matching MCO source/runbook revision.
- [ ] Define the log/event/object fields that identify this case: Node NotReady/Unknown, kubelet heartbeat or lease stale, pod state does not converge, container runtime errors, or API operations time out against one node.
- [ ] Capture sanitized examples from a test cluster or incident archive.
- [ ] Document known false positives and required evidence gaps.

## Phase 1: Read-only evidence tools
- [ ] Implement a scoped MCO log query for the affected node and incident window.
- [ ] Implement object reads for the resources named in the diagnostic commands.
- [ ] Normalize timestamps, namespace/name, node identity and resource versions.
- [ ] Redact secrets and high-risk payload fields.

## Phase 2: Reasoning and classification
- [ ] Add the case trigger and counter-evidence checks.
- [ ] Require lifecycle-stage classification before assigning a root cause.
- [ ] Return supporting evidence, contradictions, confidence and missing data.
- [ ] Distinguish one-node symptoms from cluster-wide API/control-plane symptoms.

## Phase 3: Recommendations and approval
- [ ] Encode the safe remediation path: Establish whether the host is reachable and whether API connectivity, kubelet, CRI-O, disk or hardware is the failure. Use approved node-level recovery and platform runbooks. If host logs cannot be collected through the API, use the supported out-of-band console path.
- [ ] Mark risk and approval requirements: Do not assume force-deleting pods means processes stopped on an unreachable host. Avoid repeated reboots or node deletion until workload/storage ownership and recovery strategy are known.
- [ ] Keep all mutation tools disabled in the first release.
- [ ] If approved remediation is later added, require explicit approval, audit record, rollback and post-checks.

## Phase 4: Verification and tests
- [ ] Unit tests: matching trigger, non-matching trigger, incomplete evidence and contradictory evidence.
- [ ] Integration test: gather logs and resource state using least-privilege RBAC.
- [ ] Safety test: agent refuses unapproved destructive action.
- [ ] Recovery test: verify `Node returns Ready, kubelet/runtime state is healthy, pods converge, and the MCO lifecycle can safely continue.`
- [ ] Regression test: ensure generic `MCP Updating` alone does not trigger this diagnosis.

## Release gates
- No critical safety test failures.
- No unbounded loops or retries.
- Evidence is reproducible and source-linked.
- A human reviewer can follow the diagnosis without trusting an opaque score.


## Kubernetes object observability requirements

**Scenario:** Node, kubelet or CRI-O unreachable

The agent can query only Splunk MCP and Prometheus MCP. The object evidence below must be emitted by the separate read-only object/Event collector into Splunk; do not assume direct Kubernetes API access from the agent. Existing container logs and Prometheus metrics remain complementary evidence.

### Required object evidence
- Node (Ready/pressure conditions, transition times, taints, unschedulable, resourceVersion)
- Lease in kube-node-lease namespace (holderIdentity, renewTime, leaseDurationSeconds)
- Event (node condition and pod lifecycle events)
- Pods on affected node (phase, deletionTimestamp, nodeName)
- MCP (only if node issue intersects rollout state)

### Correlation rule
Correlate Node condition transitions and Lease renewals with kubelet/CRI-O/MCC logs and Prometheus signals. Missing or stale Lease updates need time-aligned corroboration.

### Diagnosis gate
Do not conclude a node is unreachable from an old snapshot alone. Require stale lease/NotReady transitions or explicit runtime/API errors, with telemetry freshness and cluster identity checked.

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

## Delivery tasks and tests

1. Map this case to actual Splunk/Prometheus/Kubernetes tool names and schemas; do not invent connector APIs.
2. Implement typed evidence adapters and query bounds.
3. Add positive, negative, stale-evidence, wrong-cluster, tool-timeout and permission-denied fixtures.
4. Assert expected diagnosis and that no mutation capability is present.
5. Validate on synthetic fixtures, then read-only staging; record OpenShift release tested.

Case-specific test gate: Correlate Node conditions, heartbeat/lease age, kubelet/CRI-O logs and telemetry freshness. Unreachable node means process termination cannot be inferred from pod deletion.
