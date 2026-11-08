# Implementation Plan: CSI Max Volume Limit Exceeded on Node (`16-csi-max-volume-limit-exceeded`)

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Phase 0: Ground Truth & Telemetry Alignment
- [ ] Pin supported OpenShift release(s) and CSI driver volume limit specifications (Kubernetes CSINode spec, AWS EBS, MapR, Trident).
- [ ] Align trigger signals in Splunk: `index=k8s_objects` contains `reason == "FailedScheduling"` matching `(?i)0/\d+ nodes are available: \d+ node\(s\) exceed max volume count`.
- [ ] Verify that `CSINode`, `VolumeAttachment`, `Node`, and `Pod` objects are cached in the Splunk KV Store (`k8s_live_inventory_lookup`) with `managedFields` stripped.
- [ ] Confirm Prometheus metrics `kube_node_status_allocatable{resource=~"attachable_volumes.*"}` are indexed in `index=ocp_metrics`.

## Phase 1: Read-Only Evidence Tooling
- [ ] Implement the parameterized **Unified Multi-Index Splunk Search** (`query_unified_splunk_dossier`).
- [ ] Bound search time: `earliest=-1h latest=now` for logs/events/metrics; instant lookup for live KV store objects.
- [ ] Normalize timestamps, cluster ID, pending pod name, namespace, candidate node list, and active volume counts into structured state.
- [ ] Redact sensitive labels and volume source credentials.

## Phase 2: Causal Reasoning & Classification
- [ ] Extract pending replacement pods / migrating VMs and correlate with their required PVCs and storage classes.
- [ ] Implement the **Node Volume Tally Engine**:
  - Tally active `VolumeAttachment`s where `spec.nodeName == node` and `status.attached == true`.
  - Extract maximum attachable volume quota from `CSINode.spec.drivers[].allocatable.count` or `Node.status.allocatable`.
  - Calculate headroom $V_{headroom} = V_{max} - V_{used}$ across candidate nodes.
- [ ] Classify root cause:
  - **Branch 3A (Fleet Volume Capacity Exhaustion):** $\ge 90\%$ of candidate nodes have $V_{headroom} \le 0$.
  - **Branch 3B (Driver-Specific Limit):** Schedulable nodes have CPU/RAM headroom but zero volume slots for the target CSI driver.
  - **Branch 3C (CSI Driver Under-Allocated):** `CSINode` allocatable count is set to an artificially low ceiling by driver configuration.
- [ ] Exclude false positives: verify pod is still in `phase: Pending` and has not already scheduled during investigation.

## Phase 3: Two-Tier Remediation & Playbook Matching
- [ ] **Catalog Matching:**
  - Evaluate against [`remediations/PLAYBOOK_CATALOG.json`](../../remediations/PLAYBOOK_CATALOG.json).
  - Storage topology reconfiguration carries high risk of storage detachment across healthy workloads.
  - Set `playbook_match: null`.
- [ ] **Intelligent Manual CLI Fallback:**
  - Branch 3A: Output guided MachineSet scale-up commands (`oc scale machineset/...`) to add worker nodes with fresh volume slots.
  - Branch 3B: Output guided workload PVC rebalance and node drain sequencing instructions.
  - Branch 3C: Output storage vendor review commands and DaemonSet environment variable check (`MAX_VOLUMES_PER_NODE`).
- [ ] Ensure all remediation instructions include explicit pre-checks, commands, safety warnings, and post-verification checks.

## Phase 4: Verification & Acceptance Tests
- [ ] Unit tests: test scheduler denial regex parser against `exceed max volume count` and `AttachableVolumesLimitExceeded`.
- [ ] Graph test: single multi-index query completes within 10s; graph completes within 45s deadline.
- [ ] Tally test: verify node volume tally correctly calculates $V_{used}$, $V_{max}$, and $V_{headroom}$ across 10 candidate nodes.
- [ ] Safety test: verify that agent refuses autonomous mutation of `CSINode` objects or CSI driver DaemonSets.
- [ ] Post-remediation verification: pending replacement pods or OCV `virt-launcher` transition to `Running` and `Ready`, and MCP rollout proceeds.

---

## Observability & Graph Integration Contract

### Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Scheduler denial logs and CSI node driver logs.
* `index=k8s_objects` / KV Store: `CSINode` (driver allocatable counts), `VolumeAttachment` (active attachments per node), `Node` (attachable volume allocatable), and `Event` (`FailedScheduling`).
* `index=ocp_metrics`: Node attachable volume quotas and total volume metrics.

### Bounded Execution
* Max 2 Splunk tool calls total per investigation.
* 15-second per-query timeout; 45-second overall investigation deadline.
* Stop as `inconclusive` if cluster identity is ambiguous or required telemetry is unavailable.
