# Implementation Plan: OS Pivot, Reboot or Post-Reboot Verification Failure

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Phase 0: Ground Truth & Telemetry Alignment
- [ ] Pin supported OpenShift release(s) and obtain matching MCO source/runbook revision.
- [ ] Align trigger signals in Splunk: MCD pivot logs or Node `Ready: Unknown` past grace window.
- [ ] Confirm `index=ocp_logs`, `index=k8s_objects` (with `managedFields` stripped), and `index=ocp_metrics` (`machine_config_daemon_state`) are populated.
- [ ] Verify that `Node` and `Lease` objects are cached in the Splunk KV Store (`k8s_live_inventory_lookup`) for instant retrieval.

## Phase 1: Read-Only Evidence Tooling
- [ ] Implement the parameterized **Unified Multi-Index Splunk Search** (`query_unified_splunk_dossier`).
- [ ] Bound search time: `earliest=-1h latest=now` for logs/metrics; `earliest=-24h` for objects (or instant KV Store lookup).
- [ ] Normalize timestamps, cluster ID, node identity, and pivot error reasons into structured state.
- [ ] Redact secrets, authorization headers, and environment variables.

## Phase 2: Causal Reasoning & Classification
- [ ] Extract target node and error string from MCD logs.
- [ ] Verify Node lease renewal timing against reboot initiation timestamp.
- [ ] **Multi-level Root Cause Analysis:**
  - Has `rpm-ostree` failed to stage the deployment before reboot (`/boot` full)?
  - Is the host experiencing a hardware freeze or GRUB hang during reboot (> 15m)?
  - Did the host reboot, but Greenboot rolled back to the old deployment?

## Phase 3: Two-Tier Remediation & Playbook Matching
- [ ] **Catalog Matching:** Evaluate against [`remediations/PLAYBOOK_CATALOG.json`](../../remediations/PLAYBOOK_CATALOG.json):
  - Autonomous host reboot or ostree manipulation is **strictly prohibited** (`matched: false`).
- [ ] **Intelligent CLI Fallback:**
  - For pre-reboot staging: output `rpm-ostree cleanup -m` runbook.
  - For reboot hangs: output IPMI / console verification runbook with power safety warnings.
  - For post-reboot rollbacks: output Greenboot journal inspection commands.
- [ ] Keep all mutation tools disabled inside the agent; hand off execution to human SRE and hardware administrators.

## Phase 4: Verification & Acceptance Tests
- [ ] Unit tests: matching trigger, non-matching trigger, incomplete evidence, and contradictory evidence.
- [ ] Graph test: single multi-index query completes within 10s; graph completes within 45s deadline.
- [ ] Grace window test: normal reboot under 8 minutes correctly reports `not_supported: within_grace_window`.
- [ ] Safety test: verify agent strictly refuses autonomous power cycling.
- [ ] Post-remediation verification: Node `Ready: True`, `currentConfig == desiredConfig`, and state returns to `Done`.

---

## Observability & Graph Integration Contract

### Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Daemon pivot logs, systemd journal logs.
* `index=k8s_objects` / KV Store: `Node` (conditions, annotations), `Lease` in `kube-node-lease`.
* `index=ocp_metrics`: `up{job="kubelet"}`, `machine_config_daemon_state`.

### Bounded Execution
* Max 2 Splunk tool calls total per investigation.
* 15-second per-query timeout; 45-second overall investigation deadline.
* Stop as `inconclusive` if cluster identity is ambiguous or required telemetry is unavailable.
