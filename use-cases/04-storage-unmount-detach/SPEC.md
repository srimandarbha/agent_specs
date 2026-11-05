# SPEC: Storage unmount or detach stalls pod termination

## Problem statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **storage unmount or detach stalls pod termination**, using evidence from the deployed cluster rather than assuming every `Updating` pool is a drain failure.

## Trigger and scope
- Lifecycle stage: **Pod termination / storage cleanup**
- Trigger signal: Pod remains Terminating; kubelet or CSI logs mention unmount, mount, detach, `UnmountDevice`, `FailedUnmount`, or volume operation already in progress.
- In scope: read-only evidence gathering, causal classification, confidence reporting, recommended next step, and recovery verification.
- Out of scope: autonomous disruptive changes, unsupported node mutation, or declaring an upgrade healthy based on one signal.

## Required evidence
Pod PVC references, PV and VolumeAttachment state, CSI controller/node logs, node mount errors, backend health, storage network reachability.

## Diagnostic commands
```bash
oc get pod <pod> -n <namespace> -o jsonpath='{range .spec.volumes[*]}{.persistentVolumeClaim.claimName}{"\n"}{end}'
```
```bash
oc get pvc -n <namespace> -o wide
```
```bash
oc get pv <pv> -o yaml
```
```bash
oc get volumeattachments.storage.k8s.io
```
```bash
oc get pods -A -o wide | grep -Ei 'csi|portworx|dell|pure'
```
```bash
oc get events -A --sort-by=.lastTimestamp
```

## Remediation guidance
Follow the actual CSI driver's documented procedure. Repair connectivity, CSI node/controller health, or the storage backend operation; verify no workload is still using the volume before any detach. For Dell CSM, Portworx or Pure, use the driver/version-specific runbook.

## Safety constraints
Do not manually delete VolumeAttachment objects, force detach a live volume, or reboot a node with unresolved storage ownership unless storage and workload owners approve the documented recovery.
- Never fabricate output or infer a cause from MCP status alone.
- Record cluster version, timestamp, affected node, MCP, relevant namespace/pod and exact error.
- If API connectivity or evidence is insufficient, stop and report the missing data rather than recommending destructive cleanup.
- Mutation requires explicit human approval, change record, bounded scope, rollback plan and post-change validation.

## Success criteria
Unmount/detach operations complete, the old pod terminates, volume attachment state is consistent, and replacement workload health is verified.

## Acceptance tests
1. Given the trigger signal and supporting evidence, the agent identifies this use case or explicitly reports ambiguity.
2. The agent returns evidence references and distinguishes observed facts from hypotheses.
3. The agent recommends read-only checks before any mutation.
4. The agent does not execute a high-risk action without approval.
5. The agent verifies the stated success criteria after remediation.


## Kubernetes object observability requirements

**Scenario:** Storage unmount or detach stall

The agent can query only Splunk MCP and Prometheus MCP. The object evidence below must be emitted by the separate read-only object/Event collector into Splunk; do not assume direct Kubernetes API access from the agent. Existing container logs and Prometheus metrics remain complementary evidence.

### Required object evidence
- Pod (nodeName, UID, deletionTimestamp, volume references)
- PersistentVolumeClaim (namespace/name/UID, volumeName, storageClassName, accessModes, phase, conditions)
- PersistentVolume (claimRef, CSI driver, phase, safe non-secret volume identifiers)
- VolumeAttachment (attacher, nodeName, PV reference, attached, attachError, detachError)
- Event (Pod/PVC/PV/VolumeAttachment references and timestamps)
- VMI/DataVolume when the workload is an OpenShift Virtualization VM

### Correlation rule
Trace Pod volume reference → PVC → PV → VolumeAttachment and match node/driver identifiers with CSI, kubelet and storage logs. Preserve source event time and object observation time.

### Diagnosis gate
A volume object in a non-ready state is not by itself proof it blocked drain. Require a time-correlated unmount/detach error or controller evidence tied to the affected Pod/volume.

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

**Storage unmount/detach:** Correlate pod volume references with PVC/PV/VolumeAttachment and CSI node/controller logs. Do not detach volumes or delete attachments.

Acceptance criteria: (1) correct cluster and lifecycle scope are validated; (2) diagnosis references time-bounded evidence IDs; (3) missing or stale data yields an explicit unknown/inconclusive outcome; (4) no mutation tool is called; (5) the report distinguishes observed facts, hypotheses, contradictions and recommendations.
