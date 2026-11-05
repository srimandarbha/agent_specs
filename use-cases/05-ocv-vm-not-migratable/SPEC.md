# SPEC: OpenShift Virtualization VM is not live-migratable

## Problem statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **openshift virtualization vm is not live-migratable**, using evidence from the deployed cluster rather than assuming every `Updating` pool is a drain failure.

## Trigger and scope
- Lifecycle stage: **OCV eviction interceptor / drain**
- Trigger signal: MCC eviction error names `virt-launcher-eviction-interceptor.kubevirt.io` and says VMI is configured with an eviction strategy but is not live-migratable.
- In scope: read-only evidence gathering, causal classification, confidence reporting, recommended next step, and recovery verification.
- Out of scope: autonomous disruptive changes, unsupported node mutation, or declaring an upgrade healthy based on one signal.

## Required evidence
VMI conditions and migration state; VM/VMI eviction strategy; PVC/PV mode and backend capability; migration network; destination-node compatibility; VMIM history.

## Diagnostic commands
```bash
oc get vmi -A -o wide
```
```bash
oc get vmi <vmi> -n <namespace> -o yaml
```
```bash
oc get vm <vm> -n <namespace> -o yaml
```
```bash
oc get vmim -A
```
```bash
oc get pvc -n <namespace> -o wide
```
```bash
oc describe vmi <vmi> -n <namespace>
```

## Remediation guidance
Determine the exact `LiveMigratable` condition/reason. Correct the supported storage, network, CPU or scheduling constraint, or plan a controlled VM shutdown/restart with the application owner if migration is not possible. Do not change eviction strategy blindly.

## Safety constraints
Forcing eviction may interrupt a VM and its guest workload. Validate backup, guest/application recovery, maintenance window, and owner approval before a non-migrating shutdown path.
- Never fabricate output or infer a cause from MCP status alone.
- Record cluster version, timestamp, affected node, MCP, relevant namespace/pod and exact error.
- If API connectivity or evidence is insufficient, stop and report the missing data rather than recommending destructive cleanup.
- Mutation requires explicit human approval, change record, bounded scope, rollback plan and post-change validation.

## Success criteria
VMI is eligible for live migration and migration completes, or an approved maintenance plan safely stops the VM; MCC drain and VM health both recover.

## Acceptance tests
1. Given the trigger signal and supporting evidence, the agent identifies this use case or explicitly reports ambiguity.
2. The agent returns evidence references and distinguishes observed facts from hypotheses.
3. The agent recommends read-only checks before any mutation.
4. The agent does not execute a high-risk action without approval.
5. The agent verifies the stated success criteria after remediation.


## Kubernetes object observability requirements

**Scenario:** OpenShift Virtualization VM not live-migratable

The agent can query only Splunk MCP and Prometheus MCP. The object evidence below must be emitted by the separate read-only object/Event collector into Splunk; do not assume direct Kubernetes API access from the agent. Existing container logs and Prometheus metrics remain complementary evidence.

### Required object evidence
- VirtualMachineInstance (namespace/name/UID, node assignment, phase, conditions, launcher Pod relationship)
- VirtualMachine (namespace/name, runStrategy/running state and eviction strategy fields relevant to the installed API)
- VirtualMachineInstanceMigration (VMI reference, phase, conditions, start/completion times, failure reason)
- Pod (virt-launcher identity, nodeName, labels, owner references, readiness)
- PDB (when applicable) and Event
- DataVolume/PVC when disk or storage readiness is implicated

### Correlation rule
Correlate MCC drain logs with the VMI and virt-launcher Pod on the affected node, migration object status and timestamps, and any relevant VM/PDB/storage conditions. Validate fields against installed KubeVirt/OCV APIs.

### Diagnosis gate
Do not infer “not migratable” solely from VMI phase or VM existence. Require a failed/blocked migration reason or explicit migration capability/constraint evidence correlated to the drain window.

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

**OCV VM not live-migratable:** Read VM/VMI state, eviction strategy, migration policy, events and relevant virt-handler/migration logs. Do not patch VM policy or force-stop a VM.

Acceptance criteria: (1) correct cluster and lifecycle scope are validated; (2) diagnosis references time-bounded evidence IDs; (3) missing or stale data yields an explicit unknown/inconclusive outcome; (4) no mutation tool is called; (5) the report distinguishes observed facts, hypotheses, contradictions and recommendations.
