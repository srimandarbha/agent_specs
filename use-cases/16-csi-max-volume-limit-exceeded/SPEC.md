# SPEC: CSI Max Volume Limit Exceeded on Node (`16-csi-max-volume-limit-exceeded`)

## Problem Statement
The diagnostic agent must identify whether an OpenShift MCP upgrade, node drain, or OCV VM live migration is stalled because **candidate destination nodes have reached their maximum CSI volume attachment capacity** (`MAX_VOLUMES_PER_NODE` or `CSINode` `spec.drivers[].allocatable.count`), tally the active `VolumeAttachment`s against node allocatable limits across the cluster, and formulate an actionable manual CLI fallback runbook using evidence from Splunk without direct Kubernetes cluster mutation.

## Trigger and Scope
- **Lifecycle Stage:** **Post-Eviction Scheduling / OCV Live Migration / Rollout Coordination**
- **Trigger Signal:** Scheduler emits warning events in `index=k8s_objects`:
  `Warning FailedScheduling <unknown> default-scheduler 0/N nodes are available: N node(s) exceed max volume count`
  **OR** `AttachableVolumesLimitExceeded`
  **OR** OCV `VirtualMachineInstanceMigration` fails due to target node volume attachment saturation.
- **In Scope:** Read-only evidence gathering from unified Splunk multi-index search/KV store, volume tally calculation ($V_{used}$ vs $V_{max}$ across candidate nodes), confidence reporting, remediation formulation (Manual CLI fallback with MachineSet scale-out or CSI configuration guidance), and recovery verification.
- **Out of Scope:** Autonomous direct cluster mutation, patching `CSINode` objects, modifying CSI driver DaemonSets without vendor sign-off, or force-deleting workloads.

## Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Scheduler denial logs and CSI node driver logs citing volume count limits.
* `index=k8s_objects` / KV Store:
  * `Event`: `reason == "FailedScheduling"` with message matching `(?i)exceed max volume count`.
  * `CSINode`: `spec.drivers[].name`, `spec.drivers[].allocatable.count`.
  * `VolumeAttachment`: Snapshot of all volume attachments partitioned by `spec.nodeName` where `status.attached == true`.
  * `Node`: Schedulable candidate nodes (`status.allocatable["attachable-volumes-csi-*"]`, `spec.taints`, conditions).
  * `Pod`: Pending replacement pod or OCV `virt-launcher` pod requiring volume mounts.
* `index=ocp_metrics`:
  * `kube_node_status_allocatable{resource=~"attachable_volumes.*"}`.
  * `volume_manager_total_volumes`.

## Diagnostic Strategy
1. **Perception:** Ingest unified Splunk dossier in a single round-trip (< 10s query, < 45s deadline).
2. **Correlation:** Extract the pending pod / migrating VM, its attached PVCs, and the scheduler rejection `exceed max volume count`.
3. **Volume Tally Calculation:**
   - Compute $V_{used}(N)$ as the count of active `VolumeAttachment`s on each candidate node.
   - Extract $V_{max}(N)$ from `CSINode.spec.drivers[].allocatable.count` or `Node.status.allocatable`.
   - Compute headroom $V_{headroom}(N) = V_{max}(N) - V_{used}(N)$.
   - Prove mathematically whether $\ge 90\%$ of candidate nodes have $V_{headroom} \le 0$.
4. **Causal Classification:**
   - **Branch 3A (Fleet Capacity Exhaustion):** All candidate nodes hit maximum volume limit (e.g., 200/200 volumes).
   - **Branch 3B (Driver-Specific Limit):** A specific storage driver (e.g., MapR, AWS EBS, Trident) is saturated while generic nodes have capacity.
   - **Branch 3C (CSI Driver Under-Allocated):** `CSINode` allocatable count is set artificially low (e.g., 20) by driver configuration.

## Two-Tier Remediation Contract
Reconfiguring storage drivers or altering node volume density carries severe risk of storage disconnection across healthy workloads. Autonomous mutation is strictly prohibited.
- **Ansible Playbook Catalog:** `playbook_match: null`. (No automated playbook is permitted to mutate CSI driver configurations or scale infrastructure autonomously).
- **Targeted Manual CLI Fallback:**
  - *Branch 3A:* Guided SRE procedure to inspect cluster volume headroom and scale up worker MachineSets (`oc scale machineset/...`).
  - *Branch 3B:* Guided SRE procedure to identify nodes with spare driver slots and rebalance workload PVCs.
  - *Branch 3C:* Guided SRE procedure to review CSI driver DaemonSet configuration with storage vendor support before tuning `MAX_VOLUMES_PER_NODE`.

## Safety Constraints
> [!CAUTION]
> The diagnostic agent MUST NEVER execute autonomous playbooks to patch `CSINode` objects or alter CSI driver DaemonSets. In OpenShift, `CSINode` is maintained dynamically by the Kubelet; manual edits are overwritten or cause driver crashloops that detach live production PVCs.

## Success Criteria
1. Target replacement pod or OCV `virt-launcher` schedules on a candidate node with available volume slots.
2. New `VolumeAttachment` is created and reports `status.attached: true`.
3. Pod transitions to `phase: Running` and reports `Ready: True`.
4. MachineConfigPool update advances to next node.

---

## Agent Graph Integration Contract

This use case is invoked by the shared 10-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`.

### Bounded Execution
* Investigation Deadline: 45 seconds.
* Tool Budget: Max 2 Splunk tool calls per investigation.
* Output: Structured report with evidence citations, candidate node volume tally table, and guarded manual CLI fallback.
