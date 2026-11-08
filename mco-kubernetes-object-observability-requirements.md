# Observability Requirements: Kubernetes Object State for MCO Drain Troubleshooting

**Status:** Approved Architectural Direction  
**Scope:** OpenShift Fleet (150+ clusters); MCO drain troubleshooting agent  
**Evidence Pipeline:** Unified Splunk Multi-Index Search (`ocp_logs`, `k8s_objects`, `ocp_metrics`) with KV Store state caching  
**Agent Operating Mode:** Read-only diagnosis and structured remediation specification (Ansible Playbook / CLI fallback)

---

## 1. Purpose & Strategy

Container logs are forwarded to Splunk (`index=ocp_logs`) and metrics are available in Prometheus / Splunk (`index=ocp_metrics`). The missing evidence is Kubernetes object state (PDBs, finalizers, annotations).

Instead of an unconstrained API mirror, this requirement specifies the **"Golden Six" essential Kubernetes objects** to be collected via OpenTelemetry (`k8sobjectsreceiver`), pruned of `managedFields`, and cached in a Splunk KV Store.

---

## 2. The "Golden Six" Allowlist

| Object Kind | API Group / Version | What It Provides That Metrics/Logs Cannot | Excluded Fields |
|---|---|---|---|
| **`Pod`** | `core/v1` | `metadata.finalizers` (UC 03), `metadata.labels` for PDB selector matching (UC 01), `metadata.deletionTimestamp`. | `metadata.managedFields`, `spec.containers[*].env`, `spec.containers[*].envFrom` |
| **`PodDisruptionBudget`** | `policy/v1` | `spec.selector` (resolves which PDB owns a pod when multiple PDBs exist in a namespace). | `metadata.managedFields` |
| **`Node`** | `core/v1` | `metadata.annotations`: MCO drain coordination keys (`desiredDrain` vs `lastAppliedDrain` in UC 14), `spec.unschedulable`. | `metadata.managedFields`, `status.images` |
| **`VolumeAttachment`** | `storage.k8s.io/v1` | `status.attachError` and `status.detachError` to detect storage unmount deadlocks on the draining node (UC 04). | `metadata.managedFields` |
| **`MachineConfigPool`** | `machineconfiguration.openshift.io/v1` | Current vs. desired rendered config references, pool rollout progress, and paused flags (UC 10, 11, 12). | `metadata.managedFields` |
| **`Event`** | `core/v1` | Fast chronological timeline of eviction denials and scheduling rejections. | None |

---

## 3. Explicitly Excluded Objects

* ❌ **`VirtualMachine`, `VirtualMachineInstance`, `DataVolume`, `VMIM`:** OpenShift Virtualization is fully diagnosed via Prometheus metrics (`kubevirt_vmi_non_evictable`, `kubevirt_vmi_migration_*`) and the KubeVirt eviction interceptor logs in Splunk.
* ❌ **`Secrets` and `ConfigMaps`:** Strictly prohibited by InfoSec policy; zero credential ingestion.
* ❌ **`DaemonSets`:** MCO drain helper has `--ignore-daemonsets=true` hardcoded; DaemonSets are never evicted during drain.
* ❌ **`PersistentVolume` (PV):** PVC and `VolumeAttachment` provide complete diagnostic signal.
* ❌ **`Service` and `EndpointSlice`:** Webhook reachability errors are logged directly in API server logs.

---

## 4. Mapping to the 15 MCO Troubleshooting Cases

| Case | Primary Evidence Source | Object Evidence from KV Store / k8s_objects |
|---|---|---|
| 01. PDB blocks eviction | `ocp_logs` (MCC eviction denial) + `ocp_metrics` | `Pod` (labels) + `PodDisruptionBudget` (selector) |
| 02. Admission webhook failure | `ocp_logs` (API server webhook timeout log) | `Event` |
| 03. Pod termination/finalizer | `ocp_logs` (Kubelet teardown timeout) | `Pod` (`metadata.finalizers`, `deletionTimestamp`) |
| 04. Storage unmount/detach | `ocp_logs` (CSI driver logs) | `VolumeAttachment` (`detachError`) + `Pod` |
| 05. VM not live-migratable | `ocp_logs` (eviction interceptor) + `ocp_metrics` (`kubevirt_vmi_non_evictable`) | None (Metrics + Logs 100%) |
| 06. Stale virt-launcher pod | `ocp_logs` (virt-controller) + `ocp_metrics` | `Pod` |
| 07. Rescheduling/capacity | `ocp_logs` (scheduler log) + `ocp_metrics` | `Pod` (Pending status) + `Node` |
| 08. Node/kubelet/CRI-O | `ocp_logs` (journald / CRI-O) + `ocp_metrics` | `Node` |
| 09. API/etcd latency | `ocp_logs` (etcd timeouts) + `ocp_metrics` | `Event` |
| 10. MCP paused/rollout | `ocp_metrics` (`mco_machine_config_pool_paused`) | `MachineConfigPool` + `Node` |
| 11. Configuration drift | `ocp_logs` (MCD diff log) | `Node` + `MachineConfigPool` |
| 12. Rendered config failure | `ocp_logs` (Ignition/systemd failure) | `Node` + `MachineConfigPool` |
| 13. OS pivot/reboot failure | `ocp_logs` (host journald) + `ocp_metrics` | `Node` + `MachineConfigPool` |
| 14. Uncordon/drainer mismatch | `ocp_logs` (controller coordination) | `Node` (`desiredDrain` vs `lastAppliedDrain`) |
| 15. Disk pressure exhaustion | `ocp_metrics` (`DiskPressure`) + `ocp_logs` | `Node` |

---

## 5. Security & Rate-Limiting Guardrails

1. **Stripping `managedFields`:** Decreases payload size by 65%, keeping OTel memory tiny and preventing OOMKills.
2. **Read-Only Splunk Role:** Agent accesses only `ocp_logs`, `k8s_objects`, and `ocp_metrics`.
3. **Investigation Budget:** Max 2 Splunk tool calls per investigation.
4. **Remediation Separation:** The agent cannot execute mutations; it outputs structured Ansible specs (`PLAYBOOK_CATALOG.json`) or manual CLI fallback commands.
