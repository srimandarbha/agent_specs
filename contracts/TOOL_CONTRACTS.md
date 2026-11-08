# Read-Only Tool Contracts & Remediation Specification

The agent operates in a **strictly read-only mode** during evidence gathering. It interacts with Splunk using parameterized templates. It has no direct Kubernetes client, no cluster-admin tokens, and no mutation capabilities. 

All remediation is generated as a structured specification (either an Ansible Automation Platform job spec or a manual CLI runbook) and handed off to human SREs or AAP.

---

## 1. Unified Multi-Index Splunk Search (`query_unified_splunk_dossier`)

Instead of multiple sequential queries, the agent issues a single multi-index SPL search spanning container logs, K8s object snapshots/KV Store, and Prometheus metrics.

### Input Contract
* `cluster_id` (string, required, validated against cluster allowlist).
* `node_name` (string, optional, target draining node).
* `time_window`: Enforces `earliest=-1h latest=now` for logs and metrics; `earliest=-24h` for K8s objects (or direct KV Store lookup).
* `max_records`: Hard-capped at 200 records.

### Output Contract
Returns a normalized JSON list of correlated incident records:
```json
{
  "status": "ok",
  "observed_at": "2026-11-07T22:00:00Z",
  "execution_time_ms": 4200,
  "records": [
    {
      "cluster_id": "ocp-prod-01",
      "target_namespace": "payments",
      "target_resource": "payments-api-7b89-xyz",
      "first_seen": "2026-11-07T21:10:00Z",
      "last_seen": "2026-11-07T21:58:30Z",
      "controller_eviction_errors": [
        "Cannot evict pod as it would violate the pod's disruption budget."
      ],
      "objects_observed": ["Pod", "PodDisruptionBudget"],
      "pdb_disruptions_allowed": [0],
      "pdb_min_available": [1],
      "active_finalizers": [],
      "deletion_timestamp": null,
      "storage_errors": [],
      "desired_drain_annotation": ["true"],
      "last_applied_drain_annotation": ["true"],
      "relevant_metrics": [
        "kube_pod_disruption_budget_status_pod_disruptions_allowed=0"
      ]
    }
  ]
}
```

---

## 2. Splunk KV Store Lookup Contract (`k8s_live_inventory_lookup`)

For environments using the Splunk KV Store for zero-compute object state:
* **Lookup Name:** `k8s_live_inventory_lookup`
* **Input Keys:** `cluster_id`, `namespace`, `name`
* **Output Fields:** `pdb_disruptions_allowed`, `pod_finalizers`, `pod_deletion_timestamp`, `node_desired_drain`, `node_last_applied_drain`, `storage_detach_error`, `updated_at`.
* **Latency SLA:** < 50 milliseconds.

---

## 3. Bounded Broad Anomaly Search (`query_broad_anomaly_dossier`)

Used exclusively by **Track B (Exploratory Unknown Anomaly Track)** when an incident does not match any of the 16 known use cases. Executed deterministically by the Python engine (zero LLM tool calling).

### Input Contract
* `cluster_id` (string, required)
* `node_name` (string, required)
* `time_window`: Enforces `earliest=-1h latest=now`.
* `max_records`: Hard-capped at 50 records.

### SPL Query Template
```spl
(
  (index=ocp_logs cluster_id="$cluster_id$" node="$node_name$" (level=error OR level=critical OR "failed" OR "timeout" OR "cannot" OR "denied"))
  OR
  (index=k8s_objects cluster_id="$cluster_id$" resource_kind="Event" involvedObject.name="$node_name$" type="Warning")
  OR
  (index=ocp_metrics cluster_id="$cluster_id$" node="$node_name$" metric_name IN ("kube_node_status_condition", "node_memory_utilization_ratio", "node_cpu_utilization_ratio"))
)
earliest=-1h latest=now
| head 50
```

---

## 4. Remediation Output Contract

The LangGraph node `match_remediation_plan` outputs a structured payload with two mutually exclusive paths:

### Path A: Approved Remediation Matched (`ansible_pseudocode` & `aap_launch_spec`)
Returned when the diagnosed root cause matches [`remediations/PLAYBOOK_CATALOG.json`](../remediations/PLAYBOOK_CATALOG.json) and all preconditions pass. 

On **Day 1**, the agent outputs the **Ansible YAML Pseudo-Code** and verified variables without requiring live AAP/AWX integration. In the **Final Phase**, it includes the `aap_launch_spec`:

```json
{
  "remediation_type": "ANSIBLE_PLAYBOOK_PSEUDOCODE",
  "playbook_id": "playbook_pdb_scale_up",
  "risk_level": "low",
  "requires_approval": true,
  "ansible_pseudocode": [
    "- name: Day-1 Remediation: Temporarily Scale Workload to Satisfy PDB",
    "  hosts: localhost",
    "  gather_facts: false",
    "  tasks:",
    "    - name: 1. Query current scale of Deployment/payments-api",
    "      kubernetes.core.k8s_info:",
    "        kind: Deployment",
    "        name: payments-api",
    "        namespace: payments",
    "      register: workload_info",
    "    - name: 2. Scale up replica count by +1 (from 2 to 3)",
    "      kubernetes.core.k8s_scale:",
    "        kind: Deployment",
    "        name: payments-api",
    "        namespace: payments",
    "        replicas: 3",
    "    - name: 3. Wait for PDB disruptionsAllowed to become positive",
    "      kubernetes.core.k8s_info:",
    "        kind: PodDisruptionBudget",
    "        name: payments-api-pdb",
    "        namespace: payments",
    "      register: pdb_status",
    "      until: (pdb_status.resources[0].status.disruptionsAllowed | default(0)) > 0",
    "      retries: 12",
    "      delay: 5"
  ],
  "manual_cli_fallback": {
    "command": "oc -n payments scale deployment/payments-api --replicas=3",
    "verification": "oc -n payments get pdb/payments-api-pdb"
  },
  "aap_extra_vars": {
    "target_cluster": "ocp-prod-01",
    "target_namespace": "payments",
    "workload_kind": "Deployment",
    "workload_name": "payments-api",
    "target_pdb_name": "payments-api-pdb",
    "current_replicas": 2,
    "scale_to": 3
  },
  "verification_goal": "pdb_disruptions_allowed > 0 and mcc_drain_resumed == true"
}
```

### Path B: No Playbook Matched / High Risk (`manual_cli_fallback`)
Returned when no playbook exists (or the action is dangerous, such as clearing finalizers or force-deleting pods):
```json
{
  "remediation_type": "MANUAL_CLI_RUNBOOK",
  "risk_level": "high",
  "reason": "Clearing pod finalizers risks data corruption; human investigation required.",
  "pre_checks": [
    "oc -n orders get pod order-proc-xyz -o jsonpath='{.metadata.finalizers}'",
    "oc adm node-logs worker-02 --path=journal | grep order-proc-xyz"
  ],
  "remediation_steps": [
    "oc -n orders patch pod order-proc-xyz -p '{\"metadata\":{\"finalizers\":null}}' --type=merge"
  ],
  "safety_warnings": "Ensure the underlying backend task has completed before clearing.",
  "rollback_plan": "If external task hung, restart the operator controller.",
  "post_verification": "oc get pod order-proc-xyz -n orders"
}
```

### Path C: Track B Exploratory Anomaly Briefing (`EXPLORATORY_UNKNOWN_BRIEFING`)
Returned by Node 9b (`format_sre_briefing`) when the incident does not match any of the 16 known use cases:
```json
{
  "remediation_type": "EXPLORATORY_UNKNOWN_BRIEFING",
  "playbook_match": false,
  "playbook_id": null,
  "confidence": "exploratory",
  "executive_summary": "Node drain is stuck, but standard failure modes (PDBs, CSI storage, Webhooks, Finalizers, OCV migration, DiskPressure) were investigated and ruled out. Investigation of raw logs revealed that an unmanaged third-party security agent pod is holding an active kernel cgroup lock on /sys/fs/cgroup, causing CRI-O to hang during container teardown.",
  "ruled_out_standard_cases": [
    "01-pdb-eviction-blocked (PDBs report disruptionsAllowed > 0)",
    "04-storage-unmount-detach (Zero VolumeAttachment detach errors)",
    "15-disk-pressure-host-resource (Filesystem usage is < 40%)"
  ],
  "top_anomalous_signals": [
    {
      "source": "ocp_logs (Kubelet)",
      "timestamp": "2026-11-08T11:28:40Z",
      "raw_excerpt": "crio: failed to delete container cgroup ...: device or resource busy"
    }
  ],
  "manual_cli_fallback": {
    "risk_level": "medium",
    "investigation_steps": [
      "oc debug node/worker-04.prod.corp -- chroot /host lsof /sys/fs/cgroup/systemd/kubepods.slice",
      "oc adm node-logs worker-04.prod.corp --path=journal --tail=100"
    ],
    "safety_warning": "Novel anomaly. Zero automated playbooks executed. Do not force-delete pods without manual cgroup inspection."
  }
}
```

---

## 5. Error and Retry Policy

* **Transient Failures:** Retry HTTP 429, 502, 503, 504 at most once with exponential backoff (1s, 2s) + jitter.
* **Non-Retryable Errors:** Immediately halt and report `inconclusive` on authentication, permission denied, or malformed queries.
* **Budget Exhaustion:** If the Splunk query times out or fails after retry, return an explicit tool error record. Never fabricate an empty result as "no issue found".
---

## 6. Adapter contract clarification

The logical evidence adapters are `splunk_mcp` and `prometheus_mcp` by default. Actual MCP tool names and payload schemas must be discovered and pinned during integration; this repository does not assume tool names not yet verified. See `contracts/MCP_INTEGRATION.md` and `contracts/EVIDENCE_SCHEMA.md`.

A two-call total budget is not compatible with independent adapters plus an optional follow-up. Use per-adapter budgets and one global deadline. The baseline is one Splunk call and one Prometheus call when both evidence classes are required, with at most one narrowly justified follow-up if budget remains. Track B uses one bounded query and one synthesis call. A deployment that centralizes metrics in Splunk may use a different, explicitly tested budget.

The SPL sample in `intent.md` is illustrative and must not be treated as a correct resource-join implementation. Resource joins belong in the deterministic correlation engine; see `contracts/CORRELATION_ENGINE.md`.
