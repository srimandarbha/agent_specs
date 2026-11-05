# Intent: Multi-Cluster Object Observability via RHACM for MCO Drain Troubleshooting

**Status:** Approved Architectural Direction  
**Author:** SRE Automation & Platform Diagnostics Team  
**Scope:** 150+ OpenShift Clusters across 3 Datacenters (DCs)  
**Target Consumer:** SRE Diagnostic Agent (LangGraph) & Red Hat Platform Engineering Team  

---

## 1. Problem Statement & Context

The SRE team is implementing an automated diagnostic system to triage and resolve **Machine Config Operator (MCO) drain stalls and MachineConfigPool (MCP) update failures** across a fleet of 150+ OpenShift clusters located across 3 physical/cloud datacenters.

Accurate diagnosis of MCO drain failures (such as `01-pdb-eviction-blocked`, `03-pod-termination-finalizer`, and `04-storage-unmount-detach`) requires visibility into Kubernetes object states—specifically:
* PodDisruptionBudgets (PDB selectors, `currentHealthy`, `desiredHealthy`, `disruptionsAllowed`)
* Pods (readiness conditions, restart counts, finalizers, deletion timestamps)
* Nodes (readiness, taints, cordon state, MCO drain annotations)
* MachineConfigPools and MachineConfigs (rollout progress, paused state, degraded conditions)
* VolumeAttachments and PersistentVolumeClaims

---

## 2. The Anti-Pattern: Why OTel `k8sobjects` to Splunk is Rejected

The initial design considered deploying an OpenTelemetry collector with `k8sobjectsreceiver` on all 150 clusters, streaming object snapshots via Kafka into Splunk. This approach is explicitly **rejected** due to:

1. **Collector Instability & OOMKills:** The `k8sobjectsreceiver` maintains internal in-memory informers/caches. In large clusters, this results in high memory consumption and frequent OOMKills (Exit Code 137).
2. **Control-Plane Starvation:** Continuously watching and polling object states across 150 clusters creates unnecessary load on `kube-apiserver` and `etcd`.
3. **Telemetry Ingestion Lag:** The `OTel -> Kafka -> Splunk` indexing pipeline introduces 1 to 5 minutes of latency. By the time an object snapshot is searchable in Splunk, fast diagnostic timeouts (90s) have expired.
4. **Massive Licensing Waste:** Streaming full JSON specs for thousands of ephemeral pods 24/7 to Splunk incurs heavy indexing license costs for data that is only examined during rare drain alerts.

---

## 3. Core Architectural Intent: Pull-on-Demand via RHACM

Instead of a **continuous 24/7 push** to Splunk, the system will use a **pull-on-demand query model** leveraging the **Red Hat Advanced Cluster Management (RHACM)** Hubs already deployed in each of the 3 datacenters.

```
                           ┌────────────────────────┐
                           │   LangGraph SRE Agent  │
                           └───────────┬────────────┘
                                       │
            ┌──────────────────────────┼──────────────────────────┐
      HTTPS │ (Search API / GraphQL)   │                    HTTPS │
      mTLS  │                          │                          │
            ▼                          ▼                          ▼
 ┌──────────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐
 │   RHACM Hub - DC 1   │   │   RHACM Hub - DC 2   │   │   RHACM Hub - DC 3   │
 │   (Local PostgreSQL) │   │   (Local PostgreSQL) │   │   (Local PostgreSQL) │
 └──────────┬───────────┘   └──────────┬───────────┘   └──────────┬───────────┘
            │ Existing                 │ Existing                 │ Existing
            │ Klusterlet Tunnels       │ Klusterlet Tunnels       │ Klusterlet Tunnels
     ┌──────┴──────┐            ┌──────┴──────┐            ┌──────┴──────┐
     ▼      ▼      ▼            ▼      ▼      ▼            ▼      ▼      ▼
   [C-1]  [C-2]..[C-50]       [C-51] [C-52]..[C-100]    [C-101] [C-102]..[C-150]
```

### 3.1 Primary Query Path: RHACM Search API (v2)
* **Mechanism:** Spoke cluster Klusterlets already index object metadata into the local RHACM PostgreSQL database on the Hub.
* **Latency:** < 20 ms per query.
* **Impact on Spoke Clusters:** **Zero.** Spoke cluster API servers and `etcd` are never contacted during an investigation.
* **Use Case:** Answering "What is the PDB status for this pod?", "Which replicas are failing?", "Is the node cordoned?".

### 3.2 Secondary Query Path: `ManagedClusterView` (Live State Fallback)
* **Mechanism:** When real-time live verification from the spoke cluster's `kube-apiserver` is required (e.g., live Node Lease or raw MCO annotation checks), the agent submits a `ManagedClusterView` request to the Hub cluster.
* **Transport:** Routed securely over the pre-existing Klusterlet reverse tunnel. No direct spoke cluster ingress required.

---

## 4. Security & Safety Requirements

### 4.1 Strictly Read-Only (Defense in Depth)
* **Zero Secret Access:** Explicitly omit `secrets` and `configmaps` from all RBAC rules.
* **Zero Mutation:** Strictly no `create`, `update`, `patch`, or `delete` verbs (except creating transient query objects on the Hub).
* **Zero Pod Interaction:** Block `exec`, `attach`, and `portforward`.

### 4.2 Multi-Tier Rate Limiting
To ensure that an automated diagnostic loop can never degrade RHACM Hubs or spoke clusters:

1. **Ingress / Route Layer:** A dedicated OpenShift Route (`search-api-agent`) with HAProxy annotations:
   * `haproxy.router.openshift.io/rate-limit-connections.rate-http: "10"` (max 10 req/s).
   * `haproxy.router.openshift.io/rate-limit-connections.concurrent-tcp: "5"`.
2. **Kube-APIServer Layer (APF):** OpenShift API Priority and Fairness configuration on the Hub:
   * `PriorityLevelConfiguration` limits agent concurrency to 2 shares.
   * Excess calls are rejected immediately with `HTTP 429 Too Many Requests`.
3. **Agent Client Layer:** Token bucket limiter inside the LangGraph agent client throttles outbound requests to 5 req/s with exponential backoff and jitter.

### 4.3 Network & Firewall Isolation
* The agent connects **only to the 3 RHACM Hub endpoints** over port `8443` / `443` using TLS 1.3 and mTLS.
* **Zero new firewall rules** are needed between the agent and the 150 spoke clusters.

---

## 5. Division of Responsibilities

### Platform / Red Hat Administration Team:
1. Create a dedicated `ServiceAccount` (`sre-diagnostic-reader`) in namespace `open-cluster-management` on each of the 3 RHACM Hubs.
2. Bind the ServiceAccount to a read-only `ClusterRole` restricted to:
   * `search.open-cluster-management.io` (`searches`)
   * `view.open-cluster-management.io` (`managedclusterviews`)
3. Expose the rate-limited Route `search-api-agent` on each Hub.
4. Issue a long-lived ServiceAccount token (or OIDC integration) for the agent.

### SRE Diagnostic Team:
1. Implement the Python RHACM Client with client-side rate limiting and 429 backoff.
2. Integrate the RHACM client as a tool node (`query_rhacm_search`) in the LangGraph workflow.
3. Update the diagnostic skills (e.g., `01-pdb-eviction-blocked`) to query RHACM GraphQL instead of raw `oc` CLI commands or Splunk object logs.
4. Enforce an investigation budget (max 5 queries per alert investigation).

---

## 6. Non-Goals
* **No Autonomous Remediation:** The system produces root-cause diagnoses and actionable recommendations; it does not execute node uncordons, pod deletions, or PDB patches.
* **No Fleet-Wide Log Aggregation in RHACM:** Splunk remains the system of record for container logs, operator logs, and journald traces. RHACM is used exclusively for object state and metadata.
* **No Direct Spoke Cluster Credentials:** The agent will not hold direct kubeconfig files or tokens for any of the 150 spoke clusters.

---

## 7. Success & Acceptance Criteria
* [ ] Agent can query PDB and Pod state on any spoke cluster via the local RHACM Hub in < 50ms.
* [ ] Ingestion of K8s objects into OTel / Kafka / Splunk is completely disabled, saving compute and license costs.
* [ ] Attempts by the agent to access secrets or perform write operations return `HTTP 403 Forbidden` / `405 Method Not Allowed`.
* [ ] Burst traffic beyond 10 req/s receives a clean `HTTP 429 Too Many Requests` without destabilizing the RHACM Hub.
