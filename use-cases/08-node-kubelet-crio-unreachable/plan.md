# Implementation Plan: Node Becomes NotReady or Kubelet/CRI-O Unreachable

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Phase 0: Ground Truth & Telemetry Alignment
- [ ] Pin supported OpenShift release(s) and obtain matching MCO source/runbook revision.
- [ ] Align trigger signals in Splunk: Node condition `Ready` is `False` or `Unknown`, or MCC reports `error draining node.*node is not ready`.
- [ ] Confirm `index=ocp_logs`, `index=k8s_objects` (with `managedFields` stripped), and `index=ocp_metrics` are populated.
- [ ] Verify that Node objects and Lease records are cached in the Splunk KV Store (`k8s_live_inventory_lookup`) for instant retrieval.

## Phase 1: Read-Only Evidence Tooling
- [ ] Implement the parameterized **Splunk logs/object evidence query** (`query_splunk_dossier`).
- [ ] Bound search time: `earliest=-1h latest=now` for logs/metrics; `earliest=-24h` for objects (or instant KV Store lookup).
- [ ] Normalize timestamps, cluster ID, node identity, and service names into structured state.
- [ ] Redact secrets, authorization headers, and environment variables.

## Phase 2: Causal Reasoning & Classification
- [ ] Extract target node from MCC log or alert.
- [ ] Evaluate Node condition `Ready` and `kube-node-lease` renew time.
- [ ] **Multi-level Root Cause Analysis:**
  - Has `crio.service` or `kubelet.service` crashed on an otherwise accessible host?
  - Has Kubelet client TLS certificate expired during update?
  - Is the host experiencing complete power loss, kernel panic, or hypervisor freeze?

## Phase 3: Two-Tier Remediation & Playbook Matching
- [ ] **Catalog Matching:** Evaluate against [`remediations/PLAYBOOK_CATALOG.json`](../../remediations/PLAYBOOK_CATALOG.json):
  - If CRI-O service crash on a live, cordoned host is isolated:
    - Match `playbook_restart_failed_systemd_unit`.
    - Generate `aap_extra_vars`: `{ target_cluster, target_node, systemd_service_name: "crio" }`.
    - Mark risk as `medium` and require human approval before execution.
- [ ] **Intelligent CLI Fallback:** If TLS certificates expired or host is completely silent:
  - Explicitly set `playbook_match: null`.
  - Output targeted manual `oc` CLI runbook:
    ```bash
    # 1. Review pending node CSRs
    oc get csr | grep -Ei '<node>|Pending'
    # 2. Approve legitimate node CSR
    oc adm certificate approve <csr_name>
    ```
  - For unresponsive hardware: output IPMI / console verification runbook with strict anti-split-brain warnings.
- [ ] Keep all mutation tools disabled inside the agent; hand off execution to AAP or human SRE.

## Phase 4: Verification & Acceptance Tests
- [ ] Unit tests: matching trigger, non-matching trigger, incomplete evidence, and contradictory evidence.
- [ ] Graph test: single multi-index query completes within 10s; graph completes within 45s deadline.
- [ ] Playbook matching test: CRI-O daemon crash produces exact `aap_extra_vars` matching schema.
- [ ] Fallback test: unresponsive host correctly enforces physical fencing warning before any pod cleanup.
- [ ] Post-remediation verification: Node condition `Ready == True`, lease renews within 40s, and MCC resumes drain.

---

## Observability & Graph Integration Contract

### Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Host systemd journal logs (crio.service, kubelet.service), MCC drain logs.
* `index=k8s_objects` / KV Store: `Node` (conditions, annotations), `Lease` in `kube-node-lease`.
* `index=ocp_metrics`: `up{job="kubelet"}`, `kube_node_status_condition{condition="Ready"}`.

### Bounded Execution
* Max 2 Splunk tool calls total per investigation.
* 15-second per-query timeout; 45-second overall investigation deadline.
* Stop as `inconclusive` if cluster identity is ambiguous or required telemetry is unavailable.
