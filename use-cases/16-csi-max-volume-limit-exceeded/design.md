# Design: CSI Max Volume Limit Exceeded on Node (`16-csi-max-volume-limit-exceeded`)

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Design Objective
Diagnose **candidate node CSI volume attachment limit exhaustion** preventing pod rescheduling or OCV virtual machine live migration, execute an automated node volume tally engine comparing active `VolumeAttachment`s against `CSINode` allocatable thresholds, and generate a safe, non-destructive manual CLI fallback runbook for cluster administrators without direct cluster mutation.

---

## Evidence-First Flow

1. **Establish Identity & Context**
   - Cluster ID, MachineConfigPool, target draining node name, pending pod / migrating VM identity, and incident time window.
   - Pinned OpenShift version (4.12+ / 4.16+ / 4.22+ / 5.0).
2. **Confirm Lifecycle Stage**
   - Workload eviction initiated on source node, or OCV VM migration triggered, but replacement placement is blocked.
   - Scheduler emits `FailedScheduling` events citing `exceed max volume count` or `AttachableVolumesLimitExceeded`.
3. **Execute Federated Evidence Queries**
   - Query `query_splunk_dossier` for `index=ocp_logs` and `index=k8s_objects` / KV Store; query metrics separately through Prometheus MCP.
4. **Execute Node Volume Tally Engine & Causal Classification**
   - From `index=k8s_objects`:
     - Retrieve active `VolumeAttachment` objects grouped by `spec.nodeName`.
     - Retrieve `CSINode` objects and extract `spec.drivers[].allocatable.count`.
     - Retrieve `Node` objects and extract `status.allocatable["attachable-volumes-csi-*"]`.
   - Calculate headroom per candidate node: $V_{headroom} = V_{max} - V_{used}$.
   - Classify failure mode:
     - If all candidate worker nodes in pool have $V_{headroom} \le 0$ (e.g. 200/200 volumes attached across $\ge 90\%$ of nodes) $\rightarrow$ **Branch 3A: Fleet Volume Capacity Exhaustion**.
     - If only the specific CSI driver (e.g. MapR, AWS EBS, Trident) is saturated $\rightarrow$ **Branch 3B: Driver-Specific Saturation**.
     - If `allocatable.count` is set to an artificially low ceiling (e.g. 20) $\rightarrow$ **Branch 3C: CSI Driver Quota Under-Allocation**.
5. **Remediation Resolution**
   - Evaluate against `remediations/PLAYBOOK_CATALOG.json`.
   - Modifying storage driver configurations or adding compute nodes carries infrastructure and data availability risks $\rightarrow$ set `playbook_match: null`.
   - Synthesize targeted, copy-pasteable `manual_cli_fallback` runbooks containing exact pre-checks, MachineSet scale-up commands, and vendor-aligned CSI configuration guidance.
6. **Persist & Verify**
   - Record investigation state and evidence IDs in PostgreSQL (`db/migrations/001_initial.sql`).
   - Post-remediation verification: Target pod schedules on a node with available volume slots, `VolumeAttachment` transitions to `attached: true`, and pod reports `Ready: True`.

---

## State Model
`TRIGGERED -> CONTEXT_CAPTURED -> EVIDENCE_COLLECTED -> VOLUME_TALLY_CALCULATED -> ROOT_CAUSE_DIAGNOSED -> MANUAL_CLI_FALLBACK_GENERATED -> PERSISTED`

---

## Data Contract
* **Investigation Record:** `investigation_id`, `cluster_id`, `draining_node`, `blocked_pod_name`, `csi_driver_name`, `saturated_nodes_count`, `total_candidate_nodes`.
* **Evidence Citations:** `scheduler_failed_scheduling_event`, `csinode_allocatable_snapshot`, `volumeattachment_node_counts`, `node_allocatable_metrics`.
* **Remediation Specification:**
  ```json
  {
    "matched": false,
    "reason": "Cluster-wide candidate node CSI volume limit exceeded; candidate nodes lack available attachable volume slots.",
    "manual_cli_fallback": {
      "risk_level": "medium",
      "pre_checks": [ ... ],
      "remediation_steps": [ ... ],
      "safety_warning": "...",
      "verification": [ ... ]
    }
  }
  ```

---

## Guardrails
- Strictly read-only execution in the diagnostic agent.
- No direct `oc` commands executed autonomously.
- No automated patching of `CSINode` objects or CSI driver DaemonSets.
- Secret tokens and credentials stripped before persistence.
