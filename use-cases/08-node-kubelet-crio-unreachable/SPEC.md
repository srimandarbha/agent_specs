# SPEC: Node becomes NotReady or kubelet/CRI-O cannot finish drain

## Problem statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **node becomes notready or kubelet/cri-o cannot finish drain**, using evidence from the deployed cluster rather than assuming every `Updating` pool is a drain failure.

## Trigger and scope
- Lifecycle stage: **Node control plane / pod lifecycle**
- Trigger signal: Node NotReady/Unknown, kubelet heartbeat or lease stale, pod state does not converge, container runtime errors, or API operations time out against one node.
- In scope: read-only evidence gathering, causal classification, confidence reporting, recommended next step, and recovery verification.
- Out of scope: autonomous disruptive changes, unsupported node mutation, or declaring an upgrade healthy based on one signal.

## Required evidence
Node conditions and lease; kubelet/CRI-O logs; system journal; disk/inode pressure; API reachability; last transition time; machine/console health.

## Diagnostic commands
```bash
oc describe node <node>
```
```bash
oc get lease -n kube-node-lease <node> -o yaml
```
```bash
oc get pods -A --field-selector spec.nodeName=<node> -o wide
```
```bash
oc adm node-logs <node> --path=journal
```
```bash
oc get events -A --sort-by=.lastTimestamp
```

## Remediation guidance
Establish whether the host is reachable and whether API connectivity, kubelet, CRI-O, disk or hardware is the failure. Use approved node-level recovery and platform runbooks. If host logs cannot be collected through the API, use the supported out-of-band console path.

## Safety constraints
Do not assume force-deleting pods means processes stopped on an unreachable host. Avoid repeated reboots or node deletion until workload/storage ownership and recovery strategy are known.
- Never fabricate output or infer a cause from MCP status alone.
- Record cluster version, timestamp, affected node, MCP, relevant namespace/pod and exact error.
- If API connectivity or evidence is insufficient, stop and report the missing data rather than recommending destructive cleanup.
- Mutation requires explicit human approval, change record, bounded scope, rollback plan and post-change validation.

## Success criteria
Node returns Ready, kubelet/runtime state is healthy, pods converge, and the MCO lifecycle can safely continue.

## Acceptance tests
1. Given the trigger signal and supporting evidence, the agent identifies this use case or explicitly reports ambiguity.
2. The agent returns evidence references and distinguishes observed facts from hypotheses.
3. The agent recommends read-only checks before any mutation.
4. The agent does not execute a high-risk action without approval.
5. The agent verifies the stated success criteria after remediation.


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

## Case-specific diagnosis gate

**Node/kubelet/CRI-O unreachable:** Correlate Node conditions, heartbeat/lease age, kubelet/CRI-O logs and telemetry freshness. Unreachable node means process termination cannot be inferred from pod deletion.

Acceptance criteria: (1) correct cluster and lifecycle scope are validated; (2) diagnosis references time-bounded evidence IDs; (3) missing or stale data yields an explicit unknown/inconclusive outcome; (4) no mutation tool is called; (5) the report distinguishes observed facts, hypotheses, contradictions and recommendations.
