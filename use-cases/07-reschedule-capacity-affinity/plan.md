# Implementation Plan: Replacement Workloads Cannot Schedule After Eviction (`07-reschedule-capacity-affinity`)

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Phase 0: Ground Truth & Telemetry Alignment
- [ ] Pin supported OpenShift release(s) and scheduler event message formats.
- [ ] Align trigger signals in Splunk: `index=k8s_objects` contains `reason == "FailedScheduling"` with regex matching `0/\d+ nodes available`.
- [ ] Verify that `Pod`, `Node`, `Event`, and `PodDisruptionBudget` objects are cached in the Splunk KV Store (`k8s_live_inventory_lookup`) with `managedFields` stripped.
- [ ] Confirm Prometheus metrics `kube_node_status_allocatable_cpu_cores` and `kube_node_status_allocatable_memory_bytes` are indexed in `index=ocp_metrics`.

## Phase 1: Read-Only Evidence Tooling
- [ ] Implement the parameterized **Unified Multi-Index Splunk Search** (`query_unified_splunk_dossier`).
- [ ] Bound search time: `earliest=-1h latest=now` for logs/events/metrics; instant lookup for live KV store objects.
- [ ] Normalize timestamps, cluster ID, pending pod name, namespace, and scheduler denial reasons into structured state.
- [ ] Redact sensitive labels and environment variables.

## Phase 2: Causal Reasoning & Classification
- [ ] Extract pending replacement pods and correlate with their owner workload (`Deployment`, `StatefulSet`).
- [ ] Parse `FailedScheduling` events and classify root cause:
  - **Branch 3A (Capacity Starvation):** Insufficient CPU or Memory across all uncordoned nodes.
  - **Branch 3B (Hard Anti-Affinity Deadlock):** Hard `podAntiAffinity` leaves no eligible worker nodes given current replica count.
  - **Branch 3C (Taint / Storage Topology Mismatch):** Untolerated taints or zone-pinned PVC volume attachments.
- [ ] Exclude false positives: verify pod is still in `phase: Pending` and has not already scheduled during the investigation window.

## Phase 3: Two-Tier Remediation & Playbook Matching
- [ ] **Catalog Matching:**
  - Evaluate against [`remediations/PLAYBOOK_CATALOG.json`](../../remediations/PLAYBOOK_CATALOG.json).
  - Autonomous mutation of scheduling topology or infrastructure capacity is forbidden.
  - Set `playbook_match: null`.
- [ ] **Intelligent Manual CLI Fallback:**
  - Branch 3A: Output guided MachineSet scale-up commands (`oc scale machineset/...`).
  - Branch 3B: Output guided workload anti-affinity inspection and replica coordination commands (`oc scale deployment/... --replicas=...`).
  - Branch 3C: Output node taint inspection and storage zone verification commands.
- [ ] Ensure all remediation instructions include explicit pre-checks, commands, safety warnings, and post-verification checks.

## Phase 4: Verification & Acceptance Tests
- [ ] Unit tests: test scheduling failure regex parser against capacity starvation, anti-affinity deadlock, and taint mismatch logs.
- [ ] Graph test: single multi-index query completes within 10s; graph completes within 45s deadline.
- [ ] Safety test: verify that agent refuses autonomous mutation of pod affinity, node taints, or MachineSets.
- [ ] Fallback test: verify generated CLI fallback includes valid `oc` commands and rollback instructions.
- [ ] Post-remediation verification: pending replacement pods transition to `Running` and `Ready`, PDB disruption budget is restored, and MCP rollout proceeds.

---

## Observability & Graph Integration Contract

### Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Scheduler denial logs and MCC rollout progress logs.
* `index=k8s_objects` / KV Store: `Pod` (phase, requests, affinity), `Node` (allocatable, taints), `Event` (`FailedScheduling`), and `PodDisruptionBudget`.
* `index=ocp_metrics`: Node allocatable CPU/RAM and cluster utilization ratios.

### Bounded Execution
* Max 2 Splunk tool calls total per investigation.
* 15-second per-query timeout; 45-second overall investigation deadline.
* Stop as `inconclusive` if cluster identity is ambiguous or required telemetry is unavailable.
