---
skill_id: 08-node-kubelet-crio-unreachable
skill_version: 2.0.0
title: Fail-Proof Diagnosis for Node NotReady or Kubelet/CRI-O Unreachable
lifecycle_stages:
- drain
- mcp_update
trigger_signatures:
- pattern: ': Kubelet process is running but cannot register or update node lease.


    ### Step 2: Correlate Host Journal Logs & Systemd Service States

    1. Query '
  source: ocp_logs
- pattern: '(?i)(x509: certificate has expired|certificate signed by unknown authority|bootstrap
    tokens)'
  source: ocp_logs
- pattern: '(?i)(no space left on device|eviction manager: disk pressure)'
  source: ocp_logs
supported_environments:
  openshift_versions:
  - 4.12+
  - 4.16+
  - 4.22+
  - '5.0'
  mco_versions:
  - 4.12+
  components:
  - name: machine-config-controller
  - name: machine-config-daemon
  - name: kubelet
  - name: kube-apiserver
  - name: openshift-virtualization
  - name: csi-driver
required_evidence:
- dataset: ocp_logs
  kinds: &id001
  - Node
  - Lease
  - Event
  - CertificateSigningRequest
  - Pod
  max_age_seconds: 3600
- dataset: k8s_objects
  kinds: *id001
  max_age_seconds: 300
- dataset: prometheus
  metrics:
  - declared_by_skill_and_observability_matrix
  max_age_seconds: 300
freshness_limits_seconds:
  node_and_lease: 120
  pod_pdb_storage: 300
  mcp_and_operator: 600
decision_tree_version: 1.0.0
prohibited_actions:
- direct Kubernetes mutation
- force deletion
- unreviewed finalizer removal
- unapproved AAP execution
remediation_catalog_refs: []
evaluation_fixtures:
  negative: tests/fixtures/08-node-kubelet-crio-unreachable/negative_dossier.json
owner: platform-sre
status: draft
---

# Skill: Fail-Proof Diagnosis for Node NotReady or Kubelet/CRI-O Unreachable (`08-node-kubelet-crio-unreachable`)

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

**Version:** 2.0.0  
**Target Environment:** OpenShift 4.12+ / 4.16+ / 4.22+ / 5.0  
**Execution Context:** LangGraph Deterministic Diagnostic Node (`load_skill` -> `assess_evidence` -> `diagnose` -> `match_remediation_plan`)  
**Evidence Source:** Unified Splunk Multi-Index Search (`ocp_logs`, `k8s_objects` / KV Store, `ocp_metrics`)

---

## 1. Entry Gate & Activation Criteria (Fail-Safe Pre-Checks)

The agent MUST verify these conditions before activating this skill. If any check fails, immediately exit to `persist_and_report` with the stated status.

| Check | Requirement | Exit Action on Failure |
|---|---|---|
| **Cluster Identity** | Target `cluster_id` matches an authorized cluster in the registry. | Exit: `inconclusive: invalid_cluster_context` |
| **Lifecycle Stage** | MachineConfigPool is `Updating`, and target node is undergoing drain or configuration rollout. | Exit: `inconclusive: lifecycle_stage_not_updating` |
| **Trigger Signal** | Target Node condition `Ready` is `False` or `Unknown` OR MCC logs match: `(?i)(node.*is not ready|error draining node.*node is not ready|kubelet stopped posting node status|lease.*renewTime.*stale)` | Exit: `not_supported: node_is_ready_and_responsive` |

---

## 2. Step-by-Step Diagnostic Procedure (Deterministic Decision Tree)

```
                            [Start: Unified Splunk Dossier Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [Step 1: Extract Node & Lease State]          [Node Condition Ready == True]
            Node name, Ready condition, lease age         ──► Exit: not_supported
                         │
                         ▼
            [Step 2: Differentiate Control Plane vs Host Runtime]
            Evaluate Kubelet logs, CRI-O service, and network heartbeat
                         │
         ┌───────────────┼───────────────────────────────┐
         ▼               ▼                               ▼
  [Kubelet Crash/Unit]   [Kubelet TLS / CSR Failure]     [Complete Host Silence]
  CRI-O / Kubelet unit   x509 cert expired or            No host logs in 15m,
  inactive/failed        CSR pending approval            hardware/hypervisor down
         │                       │                               │
         ▼                       ▼                               ▼
  Branch 3A: Systemd     Branch 3B: Cert Renewal         Branch 3C: Host Fencing
  Service Crash          (Manual CLI CSR approval)       (Manual CLI Out-of-band)
```

### Step 1: Extract Node Condition & Heartbeat Freshness
1. In `k8s_objects` / KV Store, inspect the `Node` object:
   * Evaluate `status.conditions[?(@.type=="Ready")]`:
     * If `status == "True"`: The node is healthy. Exit to `not_supported: node_is_ready_and_responsive`.
     * If `status == "False"` or `"Unknown"`: Record `lastTransitionTime` and `message` (e.g. `Kubelet stopped posting node status`).
2. Inspect Prometheus metric in `index=ocp_metrics`:
   * `up{job="kubelet", instance="<target_node>"}`:
     * If `0`: Kubelet metric endpoint unreachable.
     * If `1`: Kubelet process is running but cannot register or update node lease.

### Step 2: Correlate Host Journal Logs & Systemd Service States
1. Query `index=ocp_logs` for node journal logs from the target node:
   * Filter for unit messages: `systemd[1]: Unit crio.service entered failed state` or `kubelet.service: Main process exited`.
   * Filter for TLS/CSR errors: `(?i)(x509: certificate has expired|certificate signed by unknown authority|bootstrap tokens)`.
   * Check for disk space exhaustion on `/var`: `(?i)(no space left on device|eviction manager: disk pressure)`.

---

## 3. Causal Sub-Tree Analysis (The Root-Cause Engine)

```
                                [Node Unreachable / NotReady]
                                              │
              ┌───────────────────────────────┼───────────────────────────────┐
              ▼                               ▼                               ▼
    [Branch 3A: CRI-O Unit Failure]  [Branch 3B: Kubelet TLS/CSR]   [Branch 3C: Host Hardware Drop]
    crio.service crashed or hung     Client certificate expired     Total power loss or hypervisor
    Host alive, journal intact       CSR pending admin approval     freeze; split-brain risk!
              │                               │                               │
              ▼                               ▼                               ▼
    Playbook: restart_systemd_unit   Playbook: null (Security Risk) Playbook: null (Split-Brain Risk)
    AAP Extra Vars: service: crio    CLI Fallback: oc adm cert      CLI Fallback: IPMI / Console
```

* **Branch 3A: CRI-O / Container Engine Unit Failure (Recoverable Daemon Crash)**
  * *Evidence:* Host is active on the network and emitting systemd journal logs to Splunk, but `crio.service` reports `ActiveState=failed` or `SIGSEGV` due to deadlocked runtime storage locks or memory exhaustion. Kubelet transitions to `NotReady` with message: `container runtime is down`.
  * *Diagnosis:* CRI-O daemon crashed while host OS and networking remain healthy. Restarting the systemd service clears the transient deadlock.
  * *Remediation Route:* **Clean Playbook Match $\rightarrow$ `playbook_restart_failed_systemd_unit`** with `systemd_service_name: "crio"`.

* **Branch 3B: Kubelet Client TLS Certificate Expiration or Pending CSR**
  * *Evidence:* Kubelet logs report `Failed to connect to apiserver: x509: certificate has expired` or `Unauthorized`. Cluster contains pending CSRs in `index=k8s_objects` matching the target node (`system:node:<node-name>`).
  * *Diagnosis:* Kubelet rotation certificate renewal failed during drain or expired before node finished updating. Kubelet is blocked from authenticating to the kube-apiserver.
  * *Remediation Route:* **DO NOT restart systemd blindly.** Route to **Manual CLI Fallback** for CSR inspection and certificate re-approval.

* **Branch 3C: Complete Host Hardware / Hypervisor / Network Isolation (Kernel Panic or Power Loss)**
  * *Evidence:* Zero log entries from the node across any subsystem for > 10 minutes. `kube-node-lease` expired > 300s. Ping and SSH fail. Hypervisor / IPMI alerts report VM powered off or kernel panic.
  * *Diagnosis:* Hard host crash or physical network partition.
  * *Remediation Route:* **CRITICAL SAFETY HALT $\rightarrow$ Manual CLI Fallback Only.**
  * *Safety Warning:* NEVER execute `oc delete node` or force-delete pods while physical power state is unverified. If the host is merely partitioned, writing processes are still active on SAN/CSI storage.

---

## 4. Remediation Resolution Rules

### Rule 1: Automated Playbook Match (`playbook_restart_failed_systemd_unit`)
**Conditions for Match:**
1. Branch 3A is satisfied (`crio.service` or allowlisted auxiliary unit in failed state).
2. Host is network reachable and logging to Splunk.
3. Node is cordoned (`spec.unschedulable == true`).

**Generated Output Spec:**
```json
{
  "matched": true,
  "playbook_id": "playbook_restart_failed_systemd_unit",
  "playbook_file": "playbooks/remediate-restart-systemd-unit.yml",
  "risk_level": "medium",
  "requires_approval": true,
  "aap_extra_vars": {
    "target_cluster": "{{ cluster_id }}",
    "target_node": "{{ node_name }}",
    "systemd_service_name": "crio"
  },
  "verification_goal": "node_condition_ready == 'True' and systemd_unit_active == true"
}
```

---

### Rule 2: Manual CLI Fallback Generation (Branch 3B - Kubelet TLS / CSR)
**Triggered when:** Kubelet client certificate is expired or CSR is pending.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Kubelet client certificate expired or unapproved; requires manual CSR validation.",
  "manual_cli_fallback": {
    "risk_level": "medium",
    "pre_checks": [
      "# 1. Check for pending CSRs matching the affected node:",
      "oc get csr | grep -Ei '{{ node_name }}|Pending'",
      "# 2. Inspect node certificate expiration dates via host log:",
      "oc adm node-logs {{ node_name }} --path=journal | grep -Ei 'x509|certificate' | tail -n 20"
    ],
    "remediation_steps": [
      "# 3. Review and approve legitimate pending node renewal CSRs:",
      "oc get csr -o go-template='{{range .items}}{{if not .status}}{{.metadata.name}}{{\"\\n\"}}{{end}}{{end}}' | xargs -r oc adm certificate approve",
      "# 4. If Kubelet needs restart after certificate renewal:",
      "oc debug node/{{ node_name }} -- chroot /host systemctl restart kubelet"
    ],
    "safety_warning": "Verify the CSR requester identity (system:node:<node_name>) before approving to prevent rogue node registration.",
    "verification": [
      "oc get node {{ node_name }} -o jsonpath='{.status.conditions[?(@.type==\"Ready\")].status}'",
      "oc get lease -n kube-node-lease {{ node_name }}"
    ]
  }
}
```

---

### Rule 3: Manual CLI Fallback Generation (Branch 3C - Hardware / Fencing)
**Triggered when:** Node is completely unresponsive (dead host / power loss).

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Host unresponsive across network; hardware failure or fencing required.",
  "manual_cli_fallback": {
    "risk_level": "critical",
    "pre_checks": [
      "# 1. Verify node lease and time of last heartbeat:",
      "oc get lease -n kube-node-lease {{ node_name }} -o yaml",
      "# 2. Check out-of-band console / IPMI / Hypervisor state:",
      "ipmitool -H {{ bmc_ip }} -U {{ bmc_user }} power status"
    ],
    "remediation_steps": [
      "# 3. Power-cycle the physical host or restart VM via hypervisor console.",
      "# 4. CRITICAL: NEVER run 'oc delete pod --force' until host power-off is 100% verified!",
      "# 5. Once power is restored, verify node returns to Ready before continuing MCO update."
    ],
    "safety_warning": "Force-deleting pods or VolumeAttachments without hardware fencing will cause silent multi-attach SAN filesystem corruption.",
    "verification": [
      "oc get node {{ node_name }} -o jsonpath='{.status.conditions[?(@.type==\"Ready\")].status}'"
    ]
  }
}
```

---

## 5. Fail-Safe Stop Conditions & Uncertainty Downgrades

The agent MUST halt and report `inconclusive` or `not_supported` if any of the following occur:

1. **Telemetry Ingestion Failure:** Splunk multi-index query fails or returns HTTP 5xx. Report: `inconclusive: telemetry_backend_unavailable`.
2. **Ambiguous Heartbeat Delay:** Node lease was renewed 15 seconds ago, but node conditions haven't caught up. Report: `inconclusive: heartbeat_transition_in_progress`.
3. **Cluster-Wide API Server Degradation:** Multiple nodes across all pools suddenly report `Unknown` simultaneously (global control plane failure, not a node issue). Report: `inconclusive: cluster_wide_apiserver_degradation_detected`.
4. **Host Fencing Uncertainty:** Host power state cannot be confirmed from telemetry. Prohibit autonomous recovery.

---

## 6. Post-Remediation Verification Contract

Whether executed via AAP playbook or manual CLI, recovery MUST be proven using these exact signals:

1. **Node Condition Restored:** `node.status.conditions[?(@.type=="Ready")].status == "True"`.
2. **Lease Renewal Fresh:** `kube-node-lease` for the node reports `renewTime` within the last 40 seconds.
3. **MCO Resumption:** `index=ocp_logs` records MCC resuming drain or MachineConfigDaemon applying updates on the restored node.
## Critical service restart profile (2026-11-08)

`kubelet` and `crio` are critical platform services, not non-critical helpers. A restart recommendation requires a confirmed service process failure, reachable host, node cordoned, certificate/CSR and network-partition causes ruled out, storage/workload impact reviewed, and explicit human approval under the catalog high-risk profile. Never restart a service based only on a missing heartbeat or stale Lease.
