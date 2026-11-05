# SPEC: Admission webhook blocks pod deletion or eviction

## Problem statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **admission webhook blocks pod deletion or eviction**, using evidence from the deployed cluster rather than assuming every `Updating` pool is a drain failure.

## Trigger and scope
- Lifecycle stage: **API admission / eviction**
- Trigger signal: MCC log or API-server log includes `failed calling webhook`, `context deadline exceeded`, `context canceled`, or an explicit webhook denial.
- In scope: read-only evidence gathering, causal classification, confidence reporting, recommended next step, and recovery verification.
- Out of scope: autonomous disruptive changes, unsupported node mutation, or declaring an upgrade healthy based on one signal.

## Required evidence
Exact webhook name and operation from API-server logs; webhook configuration rules and failurePolicy; service/endpoints; webhook pod health; API-server health and network events.

## Diagnostic commands
```bash
oc get validatingwebhookconfigurations
```
```bash
oc get mutatingwebhookconfigurations
```
```bash
oc get endpoints,endpointslices -A | grep -i <webhook-service>
```
```bash
oc get pods -A -o wide | grep -i <webhook>
```
```bash
oc -n openshift-kube-apiserver logs <apiserver-pod> --since=2h | grep -Ei 'webhook|failed calling|timeout|<webhook-name>'
```

## Remediation guidance
Repair the webhook service, endpoints, certificate, policy or network path. Determine whether it is the eviction interceptor or an unrelated webhook. Any bypass/removal must be a narrowly scoped, approved emergency change with a saved manifest, owner sign-off, time limit, and immediate restoration plan.

## Safety constraints
Deleting or disabling admission webhooks can bypass security, mutation, validation, or VM-protection controls. Do not do this as a first response.
- Never fabricate output or infer a cause from MCP status alone.
- Record cluster version, timestamp, affected node, MCP, relevant namespace/pod and exact error.
- If API connectivity or evidence is insufficient, stop and report the missing data rather than recommending destructive cleanup.
- Mutation requires explicit human approval, change record, bounded scope, rollback plan and post-change validation.

## Success criteria
The exact webhook operation succeeds without bypassing unrelated controls, MCC advances, and any emergency policy change is restored.

## Acceptance tests
1. Given the trigger signal and supporting evidence, the agent identifies this use case or explicitly reports ambiguity.
2. The agent returns evidence references and distinguishes observed facts from hypotheses.
3. The agent recommends read-only checks before any mutation.
4. The agent does not execute a high-risk action without approval.
5. The agent verifies the stated success criteria after remediation.


## Kubernetes object observability requirements

**Scenario:** Admission webhook failure

The agent can query only Splunk MCP and Prometheus MCP. The object evidence below must be emitted by the separate read-only object/Event collector into Splunk; do not assume direct Kubernetes API access from the agent. Existing container logs and Prometheus metrics remain complementary evidence.

### Required object evidence
- Event (involved object, reason/message, event time)
- ValidatingWebhookConfiguration and MutatingWebhookConfiguration (rules, operations, selectors, failurePolicy, timeoutSeconds, Service reference)
- Service and EndpointSlice (selector, ports, endpoint readiness/serving/terminating)
- Webhook Pod (namespace/name, readiness, restart/termination state, owner reference)
- Node (if webhook Pod/node health is implicated)

### Correlation rule
Correlate MCC/API-server/webhook container logs with webhook name, operation, Service reference and endpoint readiness at the incident time. Configuration alone does not establish that a webhook was unavailable.

### Diagnosis gate
Confirm only with an explicit admission/webhook failure tied to the relevant operation and corroborating configuration or availability evidence. A webhook object or unhealthy endpoint without matching failure logs is supporting evidence, not proof.

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

**Admission webhook failure:** Correlate eviction/delete request failure with webhook name, service/endpoints, timeout/failurePolicy and API audit/controller logs. Do not recommend deleting or weakening the webhook.

Acceptance criteria: (1) correct cluster and lifecycle scope are validated; (2) diagnosis references time-bounded evidence IDs; (3) missing or stale data yields an explicit unknown/inconclusive outcome; (4) no mutation tool is called; (5) the report distinguishes observed facts, hypotheses, contradictions and recommendations.
