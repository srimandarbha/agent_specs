# Per-Use-Case Observability Matrix

## Collection model

Replace the fixed “Golden Six” label with a **common baseline plus per-use-case additions**. The existing list actually contains seven kinds (Pod, PDB, Node, VolumeAttachment, MCP, MachineConfig and Event). Collect only fields needed by enabled use cases. Never collect Secrets, token values, private keys, kubeconfigs, environment-variable values, `managedFields`, or raw MachineConfig file contents.

### Common baseline

| Kind | Required fields | Applies to |
|---|---|---|
| Pod | metadata identity/UID/labels/ownerReferences/finalizers/deletionTimestamp; phase/conditions/container state; nodeName; volumes and resource requests/limits, with env values excluded | 01-08, 14-16 |
| Node | UID/resourceVersion/labels/taints; Ready/DiskPressure/PIDPressure/MemoryPressure conditions; unschedulable; allocatable/capacity; MCO annotations | 01-16 |
| Event | UID, involvedObject identity, reason, type, message, eventTime/series timestamps, reporting controller | 01-16 where relevant |
| PodDisruptionBudget | selector, minAvailable/maxUnavailable, disruptionsAllowed/currentHealthy/desiredHealthy/expectedPods | 01, 07 |

### Conditional per-use-case objects

| Kind | Required fields | Use cases | Notes |
|---|---|---|---|
| Lease | namespace/name/holderIdentity/renewTime/leaseDurationSeconds | 08, 09, 13 | Collect `kube-node-lease`; name matches Node |
| VolumeAttachment | driver, nodeName, PV name, attached, attachError/detachError, attachment metadata after redaction | 04, 16 | No credentials or secret references expanded |
| PersistentVolumeClaim | namespace/name/UID/phase/storageClass/volumeName/accessModes/volumeMode | 04, 07 | No secret data |
| PersistentVolume | name/UID/phase/storageClass/accessModes/claimRef/nodeAffinity/CSI driver and volumeHandle redacted or hashed per policy | 04, 07 | Include only where topology/attachment reasoning requires it |
| CSINode | node identity; driver name; `allocatable.count` | 16 | Required for driver-specific attach-count comparison |
| MachineConfigPool | selector, paused, maxUnavailable, status configuration, machine/updated/ready/unavailable counts and conditions | 09-14 | Include full condition reasons/messages with bounded size |
| MachineConfig | name/labels; kernelArguments; systemd units; file paths/modes/ownership; Ignition version; OS image reference | 11, 12 | Strip raw file contents and embedded secrets |
| ClusterOperator | name, versions, relatedObjects identity, conditions/reason/message | 09, 10-13 | Needed for control-plane/operator health gates |
| Service | namespace/name/selector/ports/type | 02 | Do not collect credentials |
| EndpointSlice | namespace/service label/ports/endpoints addresses/readiness/conditions/nodeName/zone | 02 | Needed to prove webhook endpoint availability |
| ValidatingWebhookConfiguration / MutatingWebhookConfiguration | webhook name, service reference, rules, failurePolicy, timeoutSeconds, admissionReviewVersions | 02 | Strip `clientConfig.caBundle`; no writes |
| Deployment / ReplicaSet | namespace/name/UID/ownerReferences/replicas/readyReplicas/selector/conditions | 02, 03, 07 | Supports webhook/operator/controller health and workload owner correlation |
| DaemonSet | namespace/name/UID/selector/desired/ready/available counts/update strategy | 04 | CSI node-driver diagnostics; DaemonSet exclusion from eviction does not make it irrelevant to diagnosis |
| CertificateSigningRequest | name/UID/username/groups/usages/conditions/expiration where supported | 08 | Never collect private keys; approval remains human-controlled |
| VirtualMachineInstance / VirtualMachineInstanceMigration | namespace/name/UID/labels/phase/nodeName/conditions/migration state and source/target identity only | 05, 06 | Optional minimal collection if metrics + launcher Pods cannot prove VM identity/state. Do not ingest full VM specs or disk data |

### Use-case mapping

| UC | Mandatory object evidence | Important metrics/logs |
|---|---|---|
| 01 PDB eviction | Pod, PDB, Event, owner workload | MCC eviction denial; PDB allowed/current/desired health; replica readiness |
| 02 Webhook | Event, Service, EndpointSlice, webhook configuration metadata, Deployment/Pod | API-server admission error, webhook controller logs, rejection count and duration |
| 03 Finalizer | Pod, Event; owner workload/controller | deletionTimestamp, finalizers, FailedKillPod, controller and CRI-O logs |
| 04 Storage detach | Pod, PVC, PV, VolumeAttachment, Node, CSI DaemonSet | kubelet unmount, CSI node/controller logs, storage metrics |
| 05 VM not migratable | launcher Pod, Node; optional VMI | eviction interceptor, non-evictable reason, migration metrics |
| 06 Stale launcher | launcher Pods, Node; optional VMI/VMIM | migration success, target launcher readiness, source/target identity |
| 07 Reschedule | Pod, owner workload, Node, Event, PVC/PV, PDB | FailedScheduling, allocatable CPU/memory, pressure and topology metrics |
| 08 Node runtime | Node, Lease, Event, optional CSR | kubelet/CRI-O journals, kubelet scrape/ready metrics, CSR state |
| 09 API/etcd | Node, Lease, MCP, ClusterOperator, Event | etcd fsync/commit/db size; API request latency; control-plane logs |
| 10 MCP paused | MCP, Node, Event, ClusterOperator | paused/updating/degraded metrics and MCC/MCD logs |
| 11 MCD drift | Node, MCP, MachineConfig, Event | MCD degraded state, drift and systemd journal logs |
| 12 Render/apply | MCP, MachineConfig, Node, Event | MCC render, Ignition and MCD apply logs |
| 13 Pivot/reboot | Node, Lease, MCP, Event | rpm-ostree/MCD/journal, kubelet availability and boot verification |
| 14 Drain coordination | Node, Pod, MCP, Event | desired/lastApplied drain annotations, audit and MCC logs |
| 15 Disk/PID | Node, Pod, Event, MCP | filesystem free bytes/inodes, pids/max, kubelet eviction and MCD write failures |
| 16 CSI max volumes | CSINode, VolumeAttachment, Node, Pod, Event; PVC/PV where needed | scheduler max-volume denial, driver metrics and attach/detach logs |

## Freshness requirements

Define freshness by evidence class, not only by one global time window. Recommended starting targets (to be tuned against measured pipeline latency): node/lease conditions <= 2 minutes; PDB/Pod/VolumeAttachment/CSINode snapshots <= 5 minutes for active incidents; MCP/MachineConfig/ClusterOperator snapshots <= 10 minutes; Events and logs retain original event times and are searched over a bounded incident window; metrics use a declared scrape timestamp and range. A stale value may be context but cannot satisfy a mandatory current-state gate.

The collector must emit `cluster_id`, resource UID, resourceVersion when available, event time, observation time and ingestion time. It must expose tombstones/deletions or periodic full snapshots so the agent can distinguish “deleted” from “not collected”.

## Collector deployment notes

The OTel `k8sobjectsreceiver` examples in older documents are illustrative, not a validated drop-in configuration. Verify receiver version, supported API kinds, field filtering syntax, watch/list RBAC, memory limits, sampling, resync behavior and deletion semantics before deployment. Add Lease, CSINode and conditional objects only after the associated use case is enabled. Use a read-only service account and no Secret list/watch permissions.
