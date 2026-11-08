# Read-Only Evidence Adapter Contracts and Remediation Output

The agent is strictly read-only during diagnosis. It has no direct Kubernetes client, cluster-admin token or mutation capability. Remediation is emitted as a recommendation and handed to a separately controlled human/AAP workflow.

## 1. Adapter topology and naming

The logical adapter boundary is **federated**:

| Adapter | Responsibility | Required capabilities |
|---|---|---|
| `splunk_mcp` | Logs, Events and normalized Kubernetes object snapshots/KV Store | bounded search, exact lookup, bounded list lookup |
| `prometheus_mcp` | Time-series metrics | instant query and bounded range query |

The tool names and JSON schemas in `contracts/mcp_schemas/` define the **agent-facing adapter contract**. They are not a claim that a connected MCP server exposes identically named tools. At integration time, discover the actual server tools, map them to these logical operations, and record the mapping in deployment configuration. Contract tests must validate the real server schema and behavior. Do not silently substitute a similarly named tool.

An optional deployment may expose metrics through Splunk if Prometheus data is already indexed there. This is an alternate adapter implementation/profile. It must preserve metric timestamps, labels and source provenance and must not change the canonical evidence contract.

## 2. Splunk logical operations

### 2.1 `query_splunk_dossier`

Returns bounded logs, Events and object snapshots for one authorized cluster and incident window.

Required input:
- `cluster_id`: registry-authorized cluster identifier.
- `time_window`: one of the configured bounded windows; default `-1h`.
- `max_records`: positive integer, hard-capped by deployment policy.

Optional input:
- `node_name`, `namespace`, `resource_kinds`, `keywords`.

The adapter must construct SPL from reviewed templates and escaped parameters. Never concatenate raw model output into SPL. Results must distinguish `ok`, `partial`, `empty`, `unsupported` and `error`. Each record must retain source index, event timestamp, ingestion timestamp and stable object identity when available.

### 2.2 `k8s_live_inventory_lookup`

This is a logical Splunk KV Store operation, not a Kubernetes API call.

Required input:
- `cluster_id`
- `kind`

Optional input:
- `namespace`
- `name` for exact lookup
- `label_selector` only if the indexed collection supports it
- `limit` and `cursor` for bounded list/pagination

At least one of `name` or a supported list mode must be supplied. Exact lookup and list lookup are distinct modes. The adapter must not require `name` for list queries, and must not interpret a zero-row result as proof of nonexistence unless collection coverage and snapshot freshness are known.

The supported kind allowlist is maintained in `contracts/mcp_schemas/splunk_mcp_tools.json` and must be kept aligned with `docs/OBSERVABILITY_MATRIX.md`. A requested kind absent from the configured collection returns `unsupported`.

### 2.3 `query_broad_anomaly_dossier`

Track B only. It runs after all 16 known skills fail their deterministic trigger gates. The Python policy layer constructs a single bounded Splunk query using the authorized cluster, incident window and optional node scope. The LLM does not generate or modify SPL. The result is exploratory evidence only and cannot match a playbook.

## 3. Prometheus logical operations

### 3.1 `query_prometheus_instant`

Accepts a reviewed query-template identifier, validated parameter values and an evaluation timestamp. Raw arbitrary PromQL is not accepted from the LLM.

### 3.2 `query_prometheus_range`

Accepts a reviewed query-template identifier, validated parameters, start/end timestamps and a bounded step. Enforce maximum range, minimum step, series cap and response-size cap. Return the actual query, query reference, warnings, sample timestamps and source endpoint identity.

Prometheus adapter errors, timeouts and partial responses must remain distinguishable from valid empty vectors/matrices.

## 4. Cross-adapter execution and budgets

- The evidence planner declares the required adapter calls for the selected skill.
- Independent Splunk and Prometheus calls may execute concurrently.
- Enforce both per-adapter call/time budgets and one end-to-end deadline.
- Retry only explicitly transient failures, at most once by default, and only if the deadline permits.
- Do not retry authorization, invalid query, schema, cluster-scope or version-gate failures.
- Persist query references and adapter outcomes for auditability.
- Never merge metrics and log/object rows into one pseudo-record merely because they share a cluster or node label. Correlation is a separate deterministic stage.

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
