# Observability Requirements: Streamlined Multi-Cluster Telemetry for MCO Drain

**Status:** Approved Architectural Direction  
**Scope:** OpenShift Fleet (150+ clusters)  
**Evidence Pipeline:** Unified Splunk Multi-Index Search (`ocp_logs`, `k8s_objects`, `ocp_metrics`) with KV Store state caching  
**Agent Operating Mode:** Read-only diagnosis and structured remediation specification (Ansible Playbook / CLI fallback)

---

## 1. Evidence Architecture Overview

To eliminate collector memory bloat, high etcd churn, and high Splunk ingest costs:
1. **Logs & Metrics Remain Primary:** Container logs (MCC, MCD, Kubelet) and Prometheus metrics (`kube-state-metrics`, KubeVirt metrics) provide 80%+ of all diagnostic signals.
2. **The "Golden Six" Kubernetes Objects:** Object collection is strictly restricted to **6 core types**. All heavy virtualization CRDs (`VirtualMachine`, `DataVolume`, `VMIM`) are dropped.
3. **Field Pruning at Ingestion:** `metadata.managedFields` and container environment variables are stripped by OpenTelemetry, reducing JSON payload size by 65%.
4. **Zero-Compute State (Splunk KV Store):** Static and slow-changing objects (PDBs, Nodes) are maintained in a Splunk KV Store (`k8s_live_inventory_lookup`) to guarantee full state visibility with zero index bucket scanning.

---

## 2. The "Golden Six" Kubernetes Object Allowlist

| Object Kind | API Group / Version | What It Provides That Metrics/Logs Cannot | Excluded Fields |
|---|---|---|---|
| **`Pod`** | `core/v1` | `metadata.finalizers` (UC 03), `metadata.labels` for PDB selector matching (UC 01), `metadata.deletionTimestamp`. | `metadata.managedFields`, `spec.containers[*].env`, `spec.containers[*].envFrom` |
| **`PodDisruptionBudget`** | `policy/v1` | `spec.selector` (resolves which PDB owns a pod when multiple PDBs exist in a namespace). | `metadata.managedFields` |
| **`Node`** | `core/v1` | `metadata.annotations`: MCO drain coordination keys (`desiredDrain` vs `lastAppliedDrain` in UC 14), `spec.unschedulable`. | `metadata.managedFields`, `status.images` |
| **`VolumeAttachment`** | `storage.k8s.io/v1` | `status.attachError` and `status.detachError` to detect storage unmount deadlocks on the draining node (UC 04). | `metadata.managedFields` |
| **`MachineConfigPool`** | `machineconfiguration.openshift.io/v1` | Current vs. desired rendered config references, pool rollout progress, and paused flags (UC 10, 11, 12). | `metadata.managedFields` |
| **`Event`** | `core/v1` | Fast chronological timeline of eviction denials and scheduling rejections. | None |

---

## 3. Explicitly Excluded Objects (What NOT to Ingest)

* ❌ **`VirtualMachine`, `VirtualMachineInstance`, `DataVolume`, `VMIM`:** OpenShift Virtualization is fully diagnosed via Prometheus metrics (`kubevirt_vmi_non_evictable`, `kubevirt_vmi_migration_*`) and the KubeVirt eviction interceptor logs in Splunk.
* ❌ **`Secrets` and `ConfigMaps`:** Strictly prohibited by InfoSec policy; zero credential ingestion.
* ❌ **`DaemonSets`:** MCO drain helper has `--ignore-daemonsets=true` hardcoded; DaemonSets are never evicted during drain.
* ❌ **`PersistentVolume` (PV):** PVC and `VolumeAttachment` provide complete diagnostic signal.
* ❌ **`Service` and `EndpointSlice`:** Webhook reachability errors are logged directly in API server logs.

---

## 4. OpenTelemetry Collector Configuration (`k8sobjectsreceiver`)

Deploy this lightweight configuration across spoke clusters to stream object state safely without OOMKills:

```yaml
receivers:
  k8sobjects:
    auth_type: serviceAccount
    objects:
      - name: pods
        mode: watch
        exclude:
          - metadata.managedFields
          - spec.containers[*].env
          - spec.containers[*].envFrom

      - name: poddisruptionbudgets
        group: policy
        mode: watch
        exclude:
          - metadata.managedFields

      - name: nodes
        mode: watch
        exclude:
          - metadata.managedFields
          - status.images

      - name: volumeattachments
        group: storage.k8s.io
        mode: watch
        exclude:
          - metadata.managedFields

      - name: machineconfigpools
        group: machineconfiguration.openshift.io
        mode: watch
        exclude:
          - metadata.managedFields

      - name: events
        mode: watch
```

---

## 5. Splunk Ingestion & KV Store Architecture

1. **`index=k8s_objects`:** Stores incoming pruned JSON snapshots/events from OpenTelemetry (short 7-day retention).
2. **`k8s_live_inventory_lookup` (KV Store):** A scheduled search runs every 10 minutes, upserting the latest record for each object into an in-memory B-Tree collection.
3. **Agent Search:** The LangGraph agent executes a single multi-index SPL search (`earliest=-1h` for logs, joined against `k8s_live_inventory_lookup`), delivering complete state correlation in <10 seconds.
