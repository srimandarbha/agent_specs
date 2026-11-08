# SPEC: Replacement Workloads Cannot Schedule After Eviction (`07-reschedule-capacity-affinity`)

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Problem Statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **replacement workloads unable to schedule after eviction**, isolate the exact scheduler constraint preventing pod placement (compute resource starvation, hard pod anti-affinity deadlock, or taint/topology zone mismatch), and generate an actionable manual CLI fallback runbook using evidence from Splunk without direct Kubernetes cluster mutation.

## Trigger and Scope
- **Lifecycle Stage:** **Post-Eviction Scheduling / Rollout Coordination**
- **Trigger Signal:** Workload eviction succeeds on the cordoned node, but replacement pods remain stuck in `phase: Pending` AND scheduler events in `index=k8s_objects` match `FailedScheduling` with reasons:
  `(?i)(0/\d+ nodes available|insufficient cpu|insufficient memory|pod anti-affinity rules unsatisfied|node\(s\) had untolerated taint|volume node affinity conflict)`.
- **In Scope:** Read-only evidence gathering from unified Splunk multi-index search/KV store, scheduler constraint isolation, causal classification, remediation formulation (Manual CLI fallback with risk assessment), and recovery verification.
- **Out of Scope:** Autonomous direct API mutation, force-deleting pods, deleting node taints, or modifying workload anti-affinity definitions without human approval.

## Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Scheduler denial logs and MCC rollout stall logs.
* `index=k8s_objects` / KV Store:
  * `Pod`: Pending replacement pods (`status.phase == "Pending"`, `spec.containers[*].resources.requests`, `spec.affinity.podAntiAffinity`, `spec.nodeSelector`, `spec.tolerations`).
  * `Node`: Schedulable worker nodes (`status.allocatable`, `spec.taints`, `metadata.labels`, conditions `Ready: True`, `DiskPressure: False`, `MemoryPressure: False`).
  * `Event`: `reason == "FailedScheduling"` with full message payload.
  * `PodDisruptionBudget`: Associated workload PDBs reporting `status.disruptionsAllowed: 0`.
* `index=ocp_metrics`:
  * `kube_node_status_allocatable_cpu_cores`, `kube_node_status_allocatable_memory_bytes`.
  * `node_cpu_utilization_ratio`, `node_memory_utilization_ratio`.

## Diagnostic Strategy
1. **Perception:** Ingest unified Splunk dossier in a single round-trip (< 10s query, < 45s deadline).
2. **Correlation:** Extract the pending pod, its owner reference, and the exact scheduler denial message from `Event` objects (`FailedScheduling`).
3. **Causal Branching:**
   - **Branch 3A (Capacity Starvation):** `Insufficient cpu` or `Insufficient memory` across all uncordoned nodes.
   - **Branch 3B (Hard Anti-Affinity Deadlock):** Workload specifies hard anti-affinity (`requiredDuringSchedulingIgnoredDuringExecution`) and replica count $N \ge$ available schedulable nodes.
   - **Branch 3C (Taint / Storage Topology Mismatch):** Untolerated worker/infra taints or single-AZ EBS/SAN volume affinity locking the pod to cordoned nodes.

## Two-Tier Remediation Contract
Scheduling constraints represent structural cluster capacity or application architectural decisions. Autonomous mutation is strictly prohibited.
- **Ansible Playbook Catalog:** `playbook_match: null`. (No automated playbook is permitted to mutate workload affinities or alter infrastructure capacity autonomously).
- **Targeted Manual CLI Fallback:**
  - *Branch 3A (Capacity):* Guided SRE procedure to inspect cluster headroom (`oc adm top nodes`) and scale up worker MachineSets (`oc scale machineset/...`).
  - *Branch 3B (Anti-Affinity):* Guided SRE procedure to coordinate with workload owners to temporarily convert hard anti-affinity to soft (`preferredDuringScheduling...`) or scale down replicas during maintenance windows.
  - *Branch 3C (Taints/Topology):* Guided SRE procedure to verify node taints and storage volume topology spread.

## Safety Constraints
> [!CAUTION]
> The diagnostic agent MUST NEVER autonomously patch `spec.affinity`, remove node taints, or delete storage volume attachments. Hard anti-affinity rules prevent split-brain and single-point-of-failure outages for mission-critical databases and microservices.

## Success Criteria
1. Target replacement pods transition from `phase: Pending` to `phase: Running` and report `Ready: True`.
2. Workload PDB reports `status.disruptionsAllowed > 0`.
3. Subsequent nodes in the MachineConfigPool proceed with drain and rollout without blocking.

---

## Agent Graph Integration Contract

This use case is invoked by the shared 10-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`.

### Bounded Execution
* Investigation Deadline: 45 seconds.
* Tool Budget: Max 2 Splunk tool calls per investigation.
* Output: Structured report with evidence citations, causal classification, and human SRE manual CLI fallback.
