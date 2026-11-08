# Design: OS Pivot, Reboot or Post-Reboot Verification Failure

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Design Objective
Diagnose **os pivot, reboot or post-reboot verification fails**, isolate whether the breakdown is a pre-reboot ostree staging failure, a physical/hypervisor reboot hang, or a post-reboot verification rollback, and generate a deterministic manual CLI fallback specification without direct cluster mutation.

---

## Evidence-First Flow

1. **Establish Identity & Context**
   - Cluster ID, MachineConfigPool, target node, and time window.
   - Pinned OpenShift release and release-matched runbook.
2. **Confirm Lifecycle Stage**
   - Trigger signal: Node unready past reboot window, or MCD logs report pivot/reboot failure.
   - Confirm active stage is `pivot`, `reboot`, or `post-reboot-verification`.
3. **Execute Federated Evidence Queries**
   - Query `query_splunk_dossier` for `index=ocp_logs` and `index=k8s_objects` / KV Store; query metrics separately through Prometheus MCP.
4. **Causal Correlation & Classification**
   - Inspect Node lease age and `state`/`reason` annotations.
   - Retrieve MCD pivot logs from Splunk.
   - Traverse causal sub-tree:
     - Branch 3A: `rpm-ostree rebase` failed before reboot? `/boot` space full or image pull error.
     - Branch 3B: Reboot executed, but host silent > 15m? Hardware, GRUB, or kernel freeze.
     - Branch 3C: Node `Ready: True`, but booted commit mismatch? Greenboot automatic rollback.
5. **Remediation Matching**
   - Automated remediation strictly prohibited (`matched: false`).
   - Generate targeted manual `oc` CLI fallback with `/boot` cleanup or out-of-band console recovery steps.
6. **Persist & Verify**
   - Record investigation state and evidence IDs in PostgreSQL (`db/migrations/001_initial.sql`).
   - Monitor for recovery post-execution: Node returns `Ready`, state returns to `Done`, currentConfig matches desiredConfig.

---

## State Model
`TRIGGERED -> CONTEXT_CAPTURED -> EVIDENCE_COLLECTED -> ROOT_CAUSE_DIAGNOSED -> REMEDIATION_MATCHED (Manual CLI Fallback) -> PERSISTED`

---

## Data Contract
* **Investigation Record:** `investigation_id`, `cluster_id`, `node_name`, `boot_stage`, `lease_age_seconds`, `current_config`, `desired_config`.
* **Evidence Citations:** `mcd_pivot_log_excerpt`, `node_lease_timestamp`, `systemd_reboot_log`.
* **Remediation Specification:**
  * `{ manual_cli_commands: [ ... ], safety_warnings: "...", rollback_steps: "..." }`.

---

## Guardrails
- Strictly read-only execution in the diagnostic agent.
- NEVER initiate power actions or reboots autonomously.
- Secret and credential values are stripped before persistence.
