# Observability Requirements: Kubernetes Object State for MCO Drain Troubleshooting

**Status:** Proposed  
**Scope:** OpenShift 4.22.x fleet; MCO drain troubleshooting agent  
**Evidence sources used by the agent:** Splunk MCP for logs/events/object history and Prometheus MCP for metrics  
**Operating mode:** Read-only diagnosis and recommendations. The agent does not execute remediation.

## 1. Purpose

Container logs are already forwarded to Splunk and metrics are available in Prometheus. The principal observability gap is Kubernetes object state and relationships.

Collect a narrowly scoped, allowlisted set of Kubernetes objects so the agent can correlate an MCO drain attempt with the affected Pod, its PodDisruptionBudget (PDB), node and MachineConfigPool (MCP), plus relevant storage, admission, and OpenShift Virtualization state.

Do **not** mirror the entire Kubernetes API. Collect only fields needed for diagnosis, correlation, and evidence history.

## 2. Collection priorities

- **P0 — Required baseline:** Node, MachineConfigPool, Pod, PodDisruptionBudget, Event.
- **P1 — Drain blocker coverage:** PersistentVolumeClaim, PersistentVolume, VolumeAttachment, MachineConfig, workload owner objects, webhook configuration and endpoint dependencies.
- **P2 — OpenShift Virtualization coverage:** VirtualMachineInstance, VirtualMachineInstanceMigration, DataVolume and associated Pod/storage relationships.
- Enable P1/P2 objects according to the failure classes the agent supports and the cost of retaining their state.

## 3. Required object inventory and field allowlists

### 3.1 Node — P0

Collect:
- `metadata.name`, `metadata.uid`, `metadata.labels`, relevant `metadata.annotations`, `metadata.resourceVersion`, creation timestamp.
- `spec.unschedulable`, `spec.taints`.
- `status.conditions`: condition type, status, reason, message, `lastHeartbeatTime`, `lastTransitionTime`.
- `status.capacity` and `status.allocatable`.

Include MCO annotations when present, including:
- `machineconfiguration.openshift.io/currentConfig`
- `machineconfiguration.openshift.io/desiredConfig`
- `machineconfiguration.openshift.io/state`
- `machineconfiguration.openshift.io/reason`
- Drain coordination annotations such as `desiredDrain` and `lastAppliedDrain` only when present in the deployed version.

**Diagnostic uses:** node readiness and pressure; cordon/uncordon coordination; MCO configuration state; scheduling/capacity analysis.

### 3.2 MachineConfigPool (MCP) — P0

Collect:
- `metadata.name`, labels, generation, resource version.
- `spec.paused`, `spec.maxUnavailable`, `spec.configuration`.
- `status.conditions`, including condition type, status, reason, message and transition time.
- `status.machineCount`, `status.updatedMachineCount`, `status.readyMachineCount`, `status.unavailableMachineCount`.
- Current/desired configuration references exposed by the deployed API version.

**Diagnostic uses:** paused rollout, degraded pool, rollout coordination, and configuration convergence.

### 3.3 Pod — P0

Collect:
- `metadata.name`, `namespace`, UID, labels, owner references, generation/resource version.
- `metadata.creationTimestamp`, `metadata.deletionTimestamp`, `metadata.finalizers`.
- `spec.nodeName`, `spec.nodeSelector`, `spec.affinity`, `spec.tolerations`.
- Container resource requests and limits.
- `status.phase`, Pod conditions, reason/message where present.
- Container waiting/terminated states, exit codes, restart counts.
- Volume references sufficient to link the Pod to PVCs; do not collect secret contents.

**Diagnostic uses:** identify the Pod involved in a drain/eviction; correlate it with PDB selectors and owners; detect termination/finalizer issues; assess rescheduling constraints and capacity.

**Data minimization:** do not export environment-variable values, Secret contents, tokens, or full Pod specs indiscriminately. Keep the field allowlist explicit.

### 3.4 PodDisruptionBudget (PDB) — P0

Collect:
- `metadata.name`, `namespace`, UID, labels, resource version.
- `spec.selector`, `spec.minAvailable`, `spec.maxUnavailable`.
- `status.currentHealthy`, `status.desiredHealthy`, `status.expectedPods`.
- `status.disruptionsAllowed`, `status.disruptedPods`, `status.observedGeneration` when available.

**Diagnostic uses:** establish whether the failing Pod matches a PDB and whether disruption was allowed around the failed eviction.

**Important:** `disruptionsAllowed: 0` alone does not prove that the PDB caused a particular drain failure. The diagnosis must correlate:
1. An eviction/drain failure for the specific Pod in logs or Events.
2. The Pod's namespace and labels.
3. The PDB selector and namespace.
4. PDB status close to the failure timestamp.
5. Cluster identity and time alignment.

If historical PDB state is unavailable, report the PDB cause as probable or inconclusive, not confirmed.

### 3.5 Event — P0

Collect:
- Event timestamp and ingestion/observation timestamp separately.
- Event type, reason, message, count, first/last observed time.
- `involvedObject` or `regarding`: kind, namespace, name, UID.
- `reportingController`, `reportingInstance`, source and related object reference when available.
- Event namespace and resource version where available.

Support both legacy core/v1 Event fields and events.k8s.io fields where present. Normalize them into one schema without losing original values.

**Diagnostic uses:** reconstruct object-level timelines and correlate controller reports with drain failures.

**Retention:** Events are ephemeral. Forward them promptly and preserve the original event time; do not rely on current Event objects to reconstruct old incidents.

### 3.6 PersistentVolumeClaim (PVC) — P1

Collect:
- `metadata.name`, namespace, UID, labels, resource version.
- `spec.volumeName`, `spec.storageClassName`, access modes, volume mode, requested storage.
- `status.phase`, capacity and relevant conditions.
- Owner/reference relationships when present.

**Diagnostic uses:** link a Pod to its claim and identify pending or unbound claims.

### 3.7 PersistentVolume (PV) — P1

Collect:
- `metadata.name`, UID, resource version.
- `spec.claimRef` namespace/name/UID.
- `spec.storageClassName`, access modes, capacity, volume mode.
- CSI driver and non-secret volume identifiers/attributes needed for correlation.
- `status.phase`.

Do not collect credentials or sensitive backend configuration.

**Diagnostic uses:** connect PVCs to backing volumes and storage-driver evidence.

### 3.8 VolumeAttachment — P1

Collect:
- `metadata.name`, UID, resource version.
- `spec.attacher`, `spec.nodeName`, `spec.source.persistentVolumeName`.
- `status.attached`, `status.attachError`, `status.detachError` when present.

**Diagnostic uses:** investigate attach/detach failures and storage operations associated with drain.

### 3.9 MachineConfig — P1

Collect:
- `metadata.name`, labels, UID, resource version, generation.
- Relevant configuration references and status fields supported by the installed API version.
- Avoid storing unrelated configuration payloads unless a specific diagnostic requires them and security review approves.

**Diagnostic uses:** compare the MCP's desired configuration with node/MCD state and investigate configuration application failures.

### 3.10 Admission webhook configuration — P1

For `ValidatingWebhookConfiguration` and `MutatingWebhookConfiguration`, collect:
- Object name, UID, resource version.
- Webhook name, rules, operations, API groups/versions, resources and scope.
- `failurePolicy`, `timeoutSeconds`, `sideEffects`, match policy and namespace/object selectors.
- Referenced Service namespace/name/path/port or URL host, as applicable.
- Relevant admission review versions.

Do not treat configuration alone as proof of a historical outage. Correlate with API server and webhook container logs and the incident timestamp.

### 3.11 Service and EndpointSlice — P1

Collect:
- Service namespace/name, selector, ports and resource version.
- EndpointSlice namespace/name, associated Service label, ports and endpoint readiness/serving/terminating conditions.
- Endpoint addresses only if required for operational correlation and allowed by policy.

**Diagnostic uses:** determine whether a webhook's referenced Service had usable endpoints. Preserve timestamped changes when investigating past incidents.

### 3.12 Workload owners — P1

Collect relevant fields for `Deployment`, `ReplicaSet`, `StatefulSet` and `DaemonSet`:
- Namespace/name, UID, labels, owner references, selector.
- Desired/current/ready/available replica counts and relevant conditions.
- Only fields needed to identify the controller and determine whether replacement Pods can be created.

**Diagnostic uses:** trace Pod ownership and understand replacement/re-scheduling behaviour.

### 3.13 ResourceQuota — P1, conditional

Collect:
- Namespace/name, hard limits and used values for relevant quota resources.
- Resource version and observation timestamp.

**Diagnostic uses:** determine whether namespace quota can prevent replacement Pods from scheduling. Collect only when quota is a supported hypothesis.

### 3.14 Namespace — P1, conditional

Collect:
- Name, UID, labels, phase, resource version.

**Diagnostic uses:** resolve namespace labels/selectors and scope related workload objects. Do not collect unrelated namespace annotations by default.

### 3.15 OpenShift Virtualization objects — P2

#### VirtualMachineInstance (VMI)
- Namespace/name, UID, labels, resource version.
- Node assignment, phase, conditions and timestamps.
- References/relationships to the launcher Pod and VM where available.

#### VirtualMachineInstanceMigration
- Namespace/name, UID, resource version.
- VMI reference, phase, conditions, start/completion timestamps and failure reason/message.

#### DataVolume
- Namespace/name, UID, resource version.
- Phase, conditions, PVC reference and relevant source/type metadata.

**Diagnostic uses:** identify non-live-migratable VM workloads, migration failures, stale `virt-launcher` Pods, and disk preparation/storage blockers. Correlate these objects with existing `virt-handler`, `virt-launcher`, migration-controller and storage logs.

## 4. Mapping to the 15 MCO troubleshooting cases

| Case | Minimum object evidence |
|---|---|
| 01. PDB blocks eviction | Pod + PDB + Event |
| 02. Admission webhook failure | Event + webhook configuration + Service + EndpointSlice |
| 03. Pod termination/finalizer | Pod + owner workload + Event |
| 04. Storage unmount/detach | Pod + PVC + PV + VolumeAttachment + Event |
| 05. VM not live-migratable | VMI + migration object + Pod + PDB + Event |
| 06. Stale `virt-launcher` after migration | Pod + VMI + migration object + Event |
| 07. Rescheduling/capacity/affinity | Pod + Node + owner workload; ResourceQuota where relevant |
| 08. Node/kubelet/CRI-O unreachable | Node + Event; logs/metrics remain primary |
| 09. API/etcd latency | Event where available; logs/metrics remain primary |
| 10. MCP paused/rollout coordination | MCP + Node |
| 11. Configuration drift/MCD degraded | Node + MCP + MachineConfig |
| 12. Rendered MachineConfig/application failure | Node + MCP + MachineConfig |
| 13. OS pivot/reboot failure | Node + MCP; logs/metrics remain primary |
| 14. Uncordon/drainer coordination | Node + Event + Pod |
| 15. Disk pressure/host resource exhaustion | Node + Pod; logs/metrics remain primary |

This mapping is a minimum evidence plan, not a guarantee that the listed objects alone prove a cause. Use logs and Prometheus metrics as complementary evidence.

## 5. Collection architecture

The agent has no direct Kubernetes API tool. A separate, read-only collector may use the Kubernetes API and publish only approved object fields and Events through the existing OTel → Kafka → Splunk pipeline. The agent continues to query Splunk MCP and Prometheus MCP only.

Recommended collector behaviour:
1. Establish an initial list/baseline for each enabled resource type.
2. Watch for changes where supported and practical.
3. Emit normalized snapshots/change records for relevant state transitions.
4. Periodically reconcile to recover missed watch events and correct drift.
5. Record collection gaps, watch restarts, API errors and last successful observation time.
6. Use least-privilege RBAC; grant no Secret access and no write permissions.
7. Validate resource kinds and fields against the actual OpenShift 4.22.x APIs and installed operators before deployment.

A watch stream alone is insufficient: it needs an initial baseline and periodic reconciliation. For resources where watch-based collection is not practical, use bounded periodic snapshots.

## 6. Normalized event/snapshot envelope

Every record should include these envelope fields where applicable:

```json
{
  "schema_version": "1",
  "cluster_id": "stable-cluster-identifier",
  "environment": "prod",
  "region": "region-or-site",
  "resource_kind": "Pod",
  "api_group": "",
  "namespace": "workload-namespace",
  "name": "pod-name",
  "uid": "kubernetes-object-uid",
  "resource_version": "observed-resource-version",
  "observed_at": "RFC3339 timestamp",
  "event_time": "RFC3339 timestamp when known",
  "record_type": "snapshot-or-change-or-event",
  "source": "kubernetes-object-collector",
  "fields": {}
}
```

The `fields` object must contain only the approved allowlist for that resource kind. `event_time` may be absent for snapshots; never fabricate it. Preserve original event payload fields where needed for debugging, subject to data-minimization rules.

## 7. Correlation and history requirements

The observability pipeline must support:
- Correlation by stable cluster ID, node, namespace, Pod name/UID, object kind/name/UID and time.
- Pod-to-PDB matching using namespace and label selector semantics, not string matching.
- Pod-to-owner and Pod-to-PVC/PV/VolumeAttachment relationships.
- MCP-to-Node-to-MachineConfig relationships.
- VMI-to-launcher-Pod-to-migration/DataVolume relationships.
- Historical state lookup at or near the drain failure time, including explicit indication when the state is unavailable.
- Separate source event time, observation time and Splunk ingestion time to measure pipeline lag.

Object names can be reused after deletion. Prefer UID when joining historical records; names alone are not a safe identity key.

## 8. Security, privacy and data minimization

- Never collect Secret contents, service-account tokens, private keys, or credential material.
- Do not collect every ConfigMap or full API audit payload by default.
- Avoid full Pod specs when a field allowlist is sufficient.
- Restrict collector RBAC to explicitly required resources and verbs, typically `get`, `list`, and `watch` for the approved resource types.
- Use TLS and the organisation's approved authentication and secret-management practices for transport.
- Apply access controls and retention policies to object snapshots and event history.
- Review whether endpoint addresses, storage identifiers, webhook URLs and configuration details are sensitive in the target environment.

## 9. Validation and acceptance criteria

Before declaring object observability production-ready, test the following:

1. **PDB block:** an eviction error can be correlated to the exact Pod and a matching PDB's historical `disruptionsAllowed` state.
2. **Selector correctness:** Pods that do not match a PDB selector are not incorrectly attributed to that PDB.
3. **Historical state:** a query can retrieve the object state close to the failure timestamp, not merely the latest snapshot.
4. **Finalizer:** Pod deletion timestamp and finalizers are visible and correlated with the drain timeline.
5. **Storage:** Pod → PVC → PV → VolumeAttachment relationships are queryable.
6. **MCP rollout:** paused/degraded/updated MCP state and relevant Node configuration annotations are queryable.
7. **Admission webhook:** webhook configuration, Service/EndpointSlice state, API server logs and webhook logs can be correlated by time.
8. **OpenShift Virtualization:** VMI, launcher Pod, migration and DataVolume relationships can be correlated.
9. **Data freshness:** event time, observation time and ingestion time are available so pipeline delays can be measured.
10. **Collection resilience:** collector restart/watch gaps are detected, and reconciliation restores a current baseline.
11. **Security:** automated checks confirm that Secret data and credentials are never emitted.
12. **Uncertainty handling:** when historical state is missing, the agent reports `probable` or `inconclusive`, rather than claiming a confirmed root cause.

## 10. Explicit non-goals

This requirement does not ask for:
- A complete Kubernetes API mirror.
- Secret or credential ingestion.
- Direct Kubernetes API access from the LangGraph agent.
- Automated remediation or mutation of cluster resources.
- Treating a single metric or current object snapshot as conclusive proof of a historical cause.

## 11. Recommended implementation order

1. Implement P0 Node, MCP, Pod, PDB and Event collection.
2. Validate PDB eviction diagnosis end-to-end, including historical joins.
3. Add PVC, PV and VolumeAttachment for storage blockers.
4. Add MachineConfig and workload owner objects for configuration and rescheduling cases.
5. Add admission webhook dependencies and OpenShift Virtualization objects.
6. Run the acceptance tests against representative incidents before expanding the allowlist fleet-wide.
