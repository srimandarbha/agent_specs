# Design: Node Becomes NotReady or Kubelet/CRI-O Unreachable

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Design Objective
Diagnose **node becomes notready or kubelet/cri-o cannot finish drain**, isolate whether the failure is a transient container runtime unit crash, a Kubelet certificate expiration, or complete host hardware isolation, and generate a deterministic remediation specification (Ansible Playbook spec or manual CLI fallback) without relying on direct cluster mutation.

---

## Evidence-First Flow

1. **Establish Identity & Context**
   - Cluster ID, MachineConfigPool, target node, and time window.
   - Pinned OpenShift release and release-matched runbook.
2. **Confirm Lifecycle Stage**
   - Trigger signal: Node reports `NotReady` or `Unknown`, or MCC reports `error draining node: node is not ready`.
   - Confirm active stage is `drain` or `updating`.
3. **Execute Federated Evidence Queries**
   - Query `query_splunk_dossier` for `index=ocp_logs` and `index=k8s_objects` / KV Store; query metrics separately through Prometheus MCP.
4. **Causal Correlation & Classification**
   - Inspect Node `status.conditions` where `type == "Ready"`.
   - Inspect Prometheus `up{job="kubelet"}` and node lease renewTime.
   - Traverse causal sub-tree:
     - Branch 3A: `crio.service` failed in journal logs? Runtime daemon crash on live host.
     - Branch 3B: Kubelet logs report x509 cert expired? Pending CSR block.
     - Branch 3C: No logs across all subsystems for > 10m? Host hardware / power drop.
5. **Remediation Matching**
   - Evaluate against `remediations/PLAYBOOK_CATALOG.json`.
   - If Branch 3A $\rightarrow$ generate `playbook_restart_failed_systemd_unit` spec with `systemd_service_name: "crio"`.
   - If Branch 3B or 3C $\rightarrow$ generate targeted manual `oc` CLI fallback with strict hardware fencing warnings.
6. **Persist & Verify**
   - Record investigation state and evidence IDs in PostgreSQL (`db/migrations/001_initial.sql`).
   - Monitor for recovery post-execution: Node returns `Ready`, lease updates, MCC drain resumes.

---

## State Model
`TRIGGERED -> CONTEXT_CAPTURED -> EVIDENCE_COLLECTED -> ROOT_CAUSE_DIAGNOSED -> REMEDIATION_MATCHED (AAP Playbook OR Manual CLI) -> PERSISTED`

---

## Data Contract
* **Investigation Record:** `investigation_id`, `cluster_id`, `node_name`, `node_condition_ready`, `lease_age_seconds`, `failed_service`.
* **Evidence Citations:** `node_condition_excerpt`, `systemd_journal_error`, `kubelet_metric_value`.
* **Remediation Specification:**
  * If automated: `{ playbook_id: "playbook_restart_failed_systemd_unit", aap_extra_vars: { ... } }`.
  * If manual: `{ manual_cli_commands: [ ... ], safety_warnings: "...", rollback_steps: "..." }`.

---

## Guardrails
- Strictly read-only execution in the diagnostic agent.
- No force deletion of pods without physical power fencing confirmation.
- No direct service restarts on uncordoned nodes.
- Secret and credential values are stripped before persistence.
