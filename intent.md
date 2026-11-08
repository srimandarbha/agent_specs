# Intent: Multi-Index Splunk Observability Architecture for MCO Drain Troubleshooting

**Status:** Approved Architectural Direction  
**Author:** SRE Automation & Platform Diagnostics Team  
**Scope:** 150+ OpenShift Clusters across 3 Datacenters (DCs)  
**Target Consumer:** SRE Diagnostic Agent (LangGraph), Splunk Administrators, and Platform Engineering  

---

## 1. Problem Statement & Context

The SRE team is implementing an automated diagnostic system to triage and resolve **Machine Config Operator (MCO) drain stalls and MachineConfigPool (MCP) update failures** across a fleet of 150+ OpenShift clusters located in 3 physical/cloud datacenters.

Diagnosing MCO drain stalls (such as `01-pdb-eviction-blocked`, `03-pod-termination-finalizer`, and `04-storage-unmount-detach`) requires correlating three distinct types of telemetry:
1. **Container Logs:** Controller error messages (e.g. MCC eviction denials, Kubelet teardown timeouts).
2. **Kubernetes Object State:** Ground-truth resource configurations and conditions (e.g. PDB selectors, `disruptionsAllowed`, pod finalizers, node drain annotations).
3. **Metrics:** Historical time series (e.g. node pressure, container crash counts, replica availability).

Enterprise access constraints prohibit direct API access or external multi-cluster management proxies. Therefore, **Splunk is the authoritative, centralized observability backend** for logs, normalized K8s object snapshots, and metrics.

---

## 2. Telemetry Sources in Splunk

The agent queries a unified Splunk instance storing telemetry partitioned across dedicated indices:

| Index Name (or alias) | Telemetry Ingested | Primary Diagnostic Purpose |
|---|---|---|
| **`ocp_logs`** | Container, operator, and journald logs | MCC eviction denial lines, Kubelet unmount logs, CRI-O errors, webhook admission logs. |
| **`k8s_objects`** | Normalized JSON snapshots & Events | Live and historical state of Pods, PDBs, Nodes, VolumeAttachments, and MCPs. |
| **`ocp_metrics`** | Ingested Prometheus metric series | Time-series metrics (`kube_pod_disruption_budget_*`, `kube_node_status_condition`, etc.). |

---

## 3. Core Architectural Intent: Unified Multi-Index SPL Query

To prevent slow, sequential round-trips that breach the 90-second LangGraph investigation deadline, the agent will **NOT** issue separate queries for logs, objects, and metrics.

Instead, the system utilizes a **Single-Query Multi-Index Pattern** across a 1-hour time window (`earliest=-1h latest=now`). This executes in a single map-reduce pass across the Splunk indexers, returning a fully correlated diagnostic dossier in **under 10 seconds**.

```
                        ┌────────────────────────┐
                        │   LangGraph SRE Agent  │
                        └───────────┬────────────┘
                                    │
                         ONE Single SPL API Call
                         (Multi-Index: earliest=-1h)
                                    │
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │                 Splunk Search Head                     │
       └───────┬────────────────────┬───────────────────┬───────┘
               │                    │                   │
               ▼                    ▼                   ▼
      ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
      │ index=ocp_logs  │  │ index=k8s_obj   │  │ index=ocp_met   │
      │ (MCC Evictions) │  │ (Pod, PDB, Node)│  │ (Prometheus TS) │
      └─────────────────┘  └─────────────────┘  └─────────────────┘
               │                    │                   │
               └────────────────────┼───────────────────┘
                                    │
                                    ▼
                        Correlated Diagnostic Dossier
                        (Returned in 1 Round-Trip)
```

### 3.1 Standardized Multi-Index SPL Template
```spl
(
  (index=ocp_logs cluster_id="$cluster_id$" ("machine-config-controller" OR "kubelet") ("Cannot evict" OR "disruption budget" OR "error when waiting for pod" OR "failed calling webhook" OR "drain"))
  OR
  (index=k8s_objects cluster_id="$cluster_id$" record_type IN ("snapshot", "change", "event") resource_kind IN ("Pod", "PodDisruptionBudget", "Node", "VolumeAttachment", "MachineConfigPool"))
  OR
  (index=ocp_metrics cluster_id="$cluster_id$" metric_name IN ("kube_pod_disruption_budget_status_pod_disruptions_allowed", "mco_machine_config_pool_degraded", "kube_node_status_condition"))
)
earliest=-1h latest=now

| eval source_category = case(
    index=="ocp_logs", "LOG_ERROR",
    index=="k8s_objects", "K8S_OBJECT",
    index=="ocp_metrics", "METRIC",
    true(), "OTHER"
  )

| spath input=fields output=pdb_disruptions_allowed path=disruptionsAllowed
| spath input=fields output=pdb_min_available path=minAvailable
| spath input=fields output=pod_finalizers path=finalizers{}
| spath input=fields output=pod_deletion_ts path=deletionTimestamp
| spath input=fields output=node_desired_drain path=annotations."machineconfiguration.openshift.io/desiredDrain"
| spath input=fields output=node_last_applied_drain path=annotations."machineconfiguration.openshift.io/lastAppliedDrain"
| spath input=fields output=storage_detach_error path=detachError

| rex field=_raw "Cannot evict pod \"(?<failing_namespace>[^\/]+)\/(?<failing_pod>[^\"]+)\": (?<eviction_error>.*)"
| rex field=_raw "error when waiting for pod \"(?<failing_namespace>[^\/]+)\/(?<failing_pod>[^\"]+)\" to terminate"

| eval target_namespace = coalesce(failing_namespace, namespace, "cluster-wide")
| eval target_resource = coalesce(failing_pod, name, resource_ref, "node-level")

| stats 
    earliest(_time) as first_seen
    latest(_time) as last_seen
    values(eviction_error) as controller_eviction_errors
    values(source_category) as categories_found
    values(resource_kind) as objects_observed
    values(pdb_disruptions_allowed) as pdb_disruptions_allowed
    values(pdb_min_available) as pdb_min_available
    values(pod_finalizers) as active_finalizers
    values(pod_deletion_ts) as deletion_timestamp
    values(storage_detach_error) as storage_errors
    values(node_desired_drain) as desired_drain_annotation
    values(node_last_applied_drain) as last_applied_drain_annotation
    values(eval(if(source_category=="METRIC", metric_name . "=" . _value, null()))) as relevant_metrics
    by cluster_id, target_namespace, target_resource
| sort - last_seen
```

---

## 4. Kubernetes Object Data Minimization (Curated Allowlist)

To prevent memory bloat in collectors and excessive ingest licensing costs in Splunk, object collection in `index=k8s_objects` is strictly limited to curated essential objects:

1. **`Pod`** (`core/v1`): Captures `finalizers`, `labels` (for selector resolution), and `deletionTimestamp`.
2. **`PodDisruptionBudget`** (`policy/v1`): Captures `spec.selector` and `disruptionsAllowed`.
3. **`Node`** (`core/v1`): Captures `metadata.annotations` (`desiredDrain`, `lastAppliedDrain`), `spec.unschedulable`, and attachable volume quotas.
4. **`VolumeAttachment`** (`storage.k8s.io/v1`): Captures `status.attachError`, `status.detachError`, and per-node attached volume counts (UC 04, 16).
5. **`MachineConfigPool`** (`machineconfiguration.openshift.io/v1`): Captures rollout state, machine counts, and paused flags (UC 10, 11, 12).
6. **`MachineConfig`** (`machineconfiguration.openshift.io/v1`): Captures target file paths (`spec.config.storage.files[*].path`), systemd unit definitions, and kernel arguments with raw base64 contents stripped (UC 11, 12).
7. **`Event`** (`core/v1`): Chronological timeline of eviction and scheduling failures.

### Explicitly Excluded Objects:
* ❌ **Secrets and ConfigMaps:** Zero secret ingestion or credential capture.
* ❌ **DaemonSets:** MCO drain helper ignores DaemonSets by design (`--ignore-daemonsets=true`).
* ❌ **OpenShift Virtualization spec objects (`VM`, `DataVolume`, `VMIM`):** OCV failures are captured via `virt-launcher-eviction-interceptor` logs and Prometheus metrics.
* ❌ **Services / EndpointSlices:** Webhook reachability errors are logged directly in API server logs.

---

## 5. Security & Rate-Limiting Guardrails

1. **Read-Only Splunk Access:** The agent’s Splunk service account is granted read-only search permissions restricted to the approved indices (`ocp_logs`, `k8s_objects`, `ocp_metrics`).
2. **Strict Time Bounds:** All queries enforce `earliest=-1h latest=now` to prevent costly full-historical scans.
3. **Investigation Call Budget:** The LangGraph agent is hard-capped at **1 primary multi-index query** per investigation, with a maximum of 1 optional follow-up query if disambiguation is required.
4. **No Mutation Capabilities:** The agent has zero Kubernetes write permissions, no cluster tokens, and no remediation execution tools.

---

## 6. Division of Responsibilities

### Splunk & Platform Administration Team:
1. Provide index names and verify retention policies for `ocp_logs`, `k8s_objects`, and `ocp_metrics`.
2. Provision a read-only Splunk REST API role/token scoped to search these indices.
3. Validate that field extractions (`spath`) are performant on the search head cluster.

### SRE Diagnostic Team:
1. Implement the unified multi-index SPL query in the LangGraph tool adapter (`query_splunk_unified_dossier`).
2. Update scenario diagnostic logic (e.g. `01-pdb-eviction-blocked`) to evaluate the aggregated dossier in a single step.
3. Implement local caching and rate-limiting inside the agent to prevent duplicate searches for concurrent alerts.

---

## 7. Success & Acceptance Criteria
* [ ] Agent completes full log, object, and metric correlation in a **single round-trip call to Splunk**.
* [ ] Query execution time in Splunk completes in **< 15 seconds** for a 1-hour window.
* [ ] PDB-blocked drain stalls are diagnosed with confirmed root cause (identifying both the PDB and the failing pod/replicas) from the single returned dossier.
* [ ] Zero Secret, ConfigMap, or credential payloads are ingested or parsed in Splunk.
---

## 8. Architecture clarification and precedence (2026-11-08)

This section supersedes earlier wording that assumes one Splunk round-trip can retrieve every evidence type. The default deployed evidence topology has separate Splunk MCP and Prometheus MCP adapters. Splunk contains logs and only those Kubernetes object snapshots/events that the telemetry pipeline has actually indexed; Prometheus MCP remains the metric source unless metrics centralization in Splunk has been explicitly deployed and contract-tested.

The agent queries the required adapters within one absolute investigation deadline, then passes normalized evidence to a deterministic correlation engine. One network call is not an architectural correctness requirement. A single Splunk multi-index query is an optimization available only in a deployment where the required logs, objects and metrics are all queryable through that Splunk backend.

The old fixed “Golden Six” label is retired. Use the common baseline plus per-use-case allowlist in `docs/OBSERVABILITY_MATRIX.md`. The original list contained seven resource kinds and omitted required resources such as Lease and CSINode.

The `<10s` or `<15s` search targets are performance objectives pending benchmark, not guarantees. Measure each adapter, end-to-end collection, LLM and persistence latency under expected concurrency. Never treat a failed adapter query or missing object history as an empty successful result.
