# Observability Requirements: All MCO Drain Troubleshooting Use Cases

**Status:** Proposed | **Target:** OpenShift 4.22.x fleet | **Agent mode:** Read-only diagnosis and recommendations

## 1. Current evidence boundary

Container logs are already forwarded to Splunk and metrics are available in Prometheus. Kubernetes object state and Kubernetes Events are the missing evidence types. The LangGraph agent has **only Splunk MCP and Prometheus MCP**; it must not assume a Kubernetes API/MCP tool is available.

A separate, read-only cluster-side collector may read an explicit allowlist of Kubernetes objects and Events and forward normalized snapshots/change records through the existing OTel → Kafka → Splunk pipeline. The agent queries those records via Splunk MCP and uses Prometheus MCP for metrics. If no collector can read the API, the agent must work with logs/metrics alone and report object-level diagnoses as probable or inconclusive when required relationships/history are missing.

## 2. Shared collection requirements

Every object snapshot/change/event should carry, where applicable:
- stable `cluster_id`, environment/region, resource kind/API group, namespace, name, UID and resourceVersion;
- source event time, observation time and Splunk ingestion time as separate timestamps;
- record type (`snapshot`, `change`, `event`), collector identity, schema version and source reference;
- only allowlisted fields, with credentials and sensitive payloads redacted or excluded.

Use initial list/baseline + watch/change capture + periodic reconciliation. Record collector errors, last-success timestamps and watch gaps. Object names can be reused, so prefer UID for historical joins. Events expire; forward promptly and preserve original event timestamps.

## 3. Global object allowlist

### P0: Baseline across most cases
- **Node:** name/UID/labels; `spec.unschedulable`, taints; Ready and pressure conditions with transition times; capacity/allocatable; relevant MCO annotations when present (`currentConfig`, `desiredConfig`, `state`, `reason`, and drain coordination annotations verified for the installed release).
- **MachineConfigPool:** name/generation; `spec.paused`, `maxUnavailable`, desired configuration; conditions and rollout counters (`machineCount`, `updatedMachineCount`, `readyMachineCount`, `unavailableMachineCount`).
- **Pod:** namespace/name/UID/labels/ownerReferences; nodeName; deletionTimestamp/finalizers; phase/conditions/container waiting or termination states; scheduling constraints and resource requests/limits; PVC references.
- **PodDisruptionBudget:** namespace/name/UID/selector; minAvailable/maxUnavailable; currentHealthy/desiredHealthy/expectedPods/disruptionsAllowed/disruptedPods/observedGeneration.
- **Event:** event type/reason/message; event time; involved/regarding object kind/namespace/name/UID; reporting controller/instance; count and related object reference.

### P1: Add for storage, admission, config and scheduling
- **PersistentVolumeClaim:** namespace/name/UID, volumeName, storageClass, access modes, phase/conditions, requested size.
- **PersistentVolume:** name/UID, claimRef, storageClass, phase, CSI driver and approved non-secret identifiers.
- **VolumeAttachment:** attacher, nodeName, PV reference, attached status and attach/detach errors.
- **MachineConfig:** name/labels/UID and configuration identity; avoid collecting full payload by default.
- **Deployment, ReplicaSet, StatefulSet, DaemonSet:** owner references, selectors and replica/availability status.
- **ResourceQuota:** relevant hard/used values when quota is a scheduling hypothesis.
- **ValidatingWebhookConfiguration / MutatingWebhookConfiguration:** rules, operations, selectors, failurePolicy, timeout, service reference.
- **Service / EndpointSlice:** selector, ports, endpoint readiness/serving/terminating state for referenced webhook services.
- **Namespace:** name/UID/labels/phase when namespace labels or scope matter.
- **Lease** in `kube-node-lease`: holderIdentity, renewTime and leaseDurationSeconds for node-heartbeat investigations.
- **ClusterOperator / ClusterVersion:** conditions/status only when broader upgrade gates are relevant.

### P2: OpenShift Virtualization
- **VirtualMachineInstance (VMI):** namespace/name/UID, node assignment, phase/conditions and launcher Pod relationship.
- **VirtualMachine:** relevant run/eviction strategy fields and identity, validated against installed API.
- **VirtualMachineInstanceMigration:** VMI reference, phase/conditions, start/completion times and failure reason.
- **DataVolume:** phase/conditions and PVC reference.

Validate exact GVKs and fields against the deployed OpenShift/KubeVirt versions. Do not assume every field exists in every release.

## 4. Case-to-object matrix

| ID | Scenario | Required object evidence |
|---|---|---|
| 01 | PDB blocks eviction | Pod + PDB + Event + owner workload; Node context |
| 02 | Admission webhook failure | Event + webhook configurations + Service + EndpointSlice + webhook Pod if available |
| 03 | Pod termination/finalizer | Pod + Event + owner workload; PVC/PV/VolumeAttachment if cleanup is storage-related |
| 04 | Storage unmount/detach | Pod + PVC + PV + VolumeAttachment + Event |
| 05 | VM not live-migratable | VMI + VM + migration + launcher Pod + Event; PDB/DataVolume/PVC when relevant |
| 06 | Stale virt-launcher after migration | Pod + VMI + migration + Event + source/target Node |
| 07 | Rescheduling/capacity/affinity | Pod + Node + owner workload + Event; ResourceQuota/PDB when relevant |
| 08 | Node/kubelet/CRI-O unreachable | Node + Lease + Event + affected Pods |
| 09 | API/etcd latency | Logs/metrics primary; Event, Node/Lease and rollout state only as corroborating symptoms |
| 10 | MCP paused/coordination | MCP + Node + MachineConfig + Event; ClusterOperator/ClusterVersion if needed |
| 11 | Config drift/MCD degraded | Node + MCP + MachineConfig + Event |
| 12 | Rendered config/apply failure | MCP + MachineConfig + Node + Event |
| 13 | OS pivot/reboot failure | Node + MCP + MachineConfig + Event + Lease when relevant |
| 14 | Uncordon/drainer coordination | Node + Event + Pod + MCP context |
| 15 | Disk pressure/host resource exhaustion | Node + Pod + Event; PVC/PV only for storage capacity issues |

## 5. Case-specific evidence rules

1. **PDB:** `disruptionsAllowed=0` alone is not proof. Correlate a specific eviction failure, Pod namespace/labels, matching PDB selector, and PDB state at the failure time.
2. **Admission:** webhook configuration alone is not proof of outage; correlate API-server/webhook logs and service endpoint state at the incident time.
3. **Finalizers:** a finalizer's presence is not proof it is stuck; correlate deletion age, owning controller and cleanup logs/events.
4. **Storage:** trace Pod → PVC → PV → VolumeAttachment and require time-correlated CSI/kubelet/controller errors.
5. **OCV migration:** correlate VMI, launcher Pod and migration status/timestamps; validate installed API fields.
6. **Scheduling:** Pending alone does not prove capacity; use scheduler Events/reasons, node allocatable/taints/labels, affinity and quota.
7. **Node unreachable:** use Node condition transitions, Lease renewTime, logs and metrics; stale snapshots alone are insufficient.
8. **API/etcd:** logs and latency/error metrics remain primary; object status is corroborating only.
9. **MCP/config:** paused/Updating or current/desired config mismatch alone may be normal during rollout; correlate MCO/MCD logs and lifecycle timing.
10. **Reboot/pivot:** account for expected reboot heartbeat gaps; require failure to return/verify plus corroborating evidence.
11. **Uncordon coordination:** preserve timestamped annotation/schedulability history; a current snapshot may miss a race.
12. **Disk pressure:** distinguish node filesystem pressure from PVC/backend capacity and avoid blaming a Pod without supporting eviction/ephemeral-storage evidence.

## 6. Agent/tool contract

- Agent evidence tools: **Splunk MCP and Prometheus MCP only**.
- Object collector: separate component, read-only API access, allowlisted fields and resources, no Secret reads and no write verbs.
- Splunk MCP queries structured object snapshots/change records/Events and existing container logs.
- Prometheus MCP queries validated metrics. Missing series is `unknown`, not zero.
- A failed query/tool call is a tool error, not evidence that a fault is absent.
- Every hypothesis cites evidence IDs and lists contradictory/missing evidence.
- Report `confirmed`, `probable`, `not_supported`, or `inconclusive`; use `confirmed` only when the scenario's evidence gate is satisfied.
- If required historical object state was not retained, say so explicitly and do not reconstruct it from a current snapshot.

## 7. Security and minimization

- No Secret data, tokens, private keys or credentials.
- No full API mirror, full Pod specs, arbitrary ConfigMaps or broad API audit payloads by default.
- RBAC limited to `get`, `list`, and optionally `watch` on approved resource types. No create/update/patch/delete/exec/attach/port-forward/proxy/impersonation.
- Apply TLS, approved authentication, retention controls and access control to object history.
- Review endpoint addresses, storage identifiers, webhook URLs and configuration metadata for sensitivity.

## 8. Acceptance tests

- PDB diagnosis rejects selector mismatch and stale/current-only PDB evidence.
- Webhook diagnosis requires matching API-server/webhook failure evidence.
- Finalizer diagnosis links finalizer/termination state to the responsible cleanup path.
- Storage diagnosis links Pod/PVC/PV/VolumeAttachment and relevant errors.
- OCV diagnosis correlates VMI, launcher Pod and migration timeline.
- Scheduling diagnosis identifies a concrete unsatisfied constraint.
- Node-unreachable diagnosis checks Lease freshness and Node transitions.
- API/etcd diagnosis is supported by logs/metrics, not object status alone.
- MCP/config/pivot/uncordon cases use version-appropriate annotations and time-correlated lifecycle evidence.
- Collector gaps and ingestion delay are observable.
- Secret data is absent from emitted records.
- Missing history or tool failure results in probable/inconclusive, never fabricated certainty.

## 9. Implementation order

1. P0 Node, MCP, Pod, PDB and Event.
2. Validate case 01 end-to-end and confirm object history can be queried from Splunk.
3. Add storage objects and owner workloads.
4. Add webhook dependencies, Lease, MachineConfig and rollout status objects.
5. Add OCV objects and scenario-specific acceptance tests.
6. Roll out progressively; measure event/object freshness, ingestion lag, volume, retention and collector gaps before fleet-wide enablement.
