# Implementation Plan: OpenShift Virtualization VM Is Not Live-Migratable

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Phase 0: Ground Truth & Telemetry Alignment
- [ ] Pin supported OpenShift release(s) and obtain matching MCO source/runbook revision.
- [ ] Align trigger signals in Splunk: MCC eviction log contains `virt-launcher-eviction-interceptor.kubevirt.io` denial.
- [ ] Confirm `index=ocp_logs`, `index=k8s_objects` (with `managedFields` stripped), and `index=ocp_metrics` (`kubevirt_vmi_non_evictable`) are populated.
- [ ] Verify that Pod objects (with `vm.kubevirt.io/name` labels) and Nodes are cached in the Splunk KV Store (`k8s_live_inventory_lookup`) for instant retrieval.

## Phase 1: Read-Only Evidence Tooling
- [ ] Implement the parameterized **Splunk logs/object evidence query** (`query_splunk_dossier`).
- [ ] Bound search time: `earliest=-1h latest=now` for logs/metrics; `earliest=-24h` for objects (or instant KV Store lookup).
- [ ] Normalize timestamps, cluster ID, VM name, and launcher pod names into structured state.
- [ ] Redact secrets, authorization headers, and environment variables.

## Phase 2: Causal Reasoning & Classification
- [ ] Extract failing pod, namespace, and VM name from MCC log.
- [ ] Query Prometheus metric `kubevirt_vmi_non_evictable{vmi="<vm_name>"}`.
- [ ] **Multi-level Root Cause Analysis:**
  - Is the VM blocked by non-shared storage (`DisksNotMigratable`)?
  - Is the VM pinned to host hardware/GPU (`HostDevicesNotMigratable`)?
  - Did live migration fail due to lack of schedulable target nodes?

## Phase 3: Two-Tier Remediation & Playbook Matching
- [ ] **Catalog Matching:** Evaluate against [`remediations/PLAYBOOK_CATALOG.json`](../../remediations/PLAYBOOK_CATALOG.json):
  - Autonomous mutation of VM state is **strictly prohibited** (`matched: false`).
- [ ] **Intelligent CLI Fallback:**
  - For non-shared storage: output runbook for controlled guest shutdown (`virtctl stop`) or PVC migration.
  - For host devices / GPU: output maintenance window runbook with guest backup reminders.
- [ ] Keep all mutation tools disabled inside the agent; hand off execution to human SRE and workload owner.

## Phase 4: Verification & Acceptance Tests
- [ ] Unit tests: matching trigger, non-matching trigger, incomplete evidence, and contradictory evidence.
- [ ] Graph test: single multi-index query completes within 10s; graph completes within 45s deadline.
- [ ] Safety test: verify agent strictly refuses autonomous VM shutdown or eviction strategy patching.
- [ ] Fallback test: non-shared storage correctly outputs planned shutdown runbook with rollback instructions.
- [ ] Post-remediation verification: Launcher pod terminated from node, and MCC resumes drain.

---

## Observability & Graph Integration Contract

### Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Controller eviction logs, virt-handler migration logs.
* `index=k8s_objects` / KV Store: `Pod` (labels, volumes), `Node` (cordon status).
* `index=ocp_metrics`: `kubevirt_vmi_non_evictable{reason=~".*"}`, `kubevirt_vmi_migration_status`.

### Bounded Execution
* Max 2 Splunk tool calls total per investigation.
* 15-second per-query timeout; 45-second overall investigation deadline.
* Stop as `inconclusive` if cluster identity is ambiguous or required telemetry is unavailable.
