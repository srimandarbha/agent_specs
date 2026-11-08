# Design: Storage Unmount or Detach Stalls Pod Termination

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Design Objective
Diagnose **storage unmount or detach stalls pod termination**, isolate whether the failure is a local CSI node daemon hang, a cloud/SAN array lock, or a busy host mount, and generate a deterministic remediation specification (Ansible Playbook spec or manual CLI fallback) without direct cluster mutation.

---

## Evidence-First Flow

1. **Establish Identity & Context**
   - Cluster ID, MachineConfigPool, target node, and time window.
   - Pinned OpenShift release and storage CSI driver version.
2. **Confirm Lifecycle Stage**
   - Trigger signal: Kubelet or CSI logs in `ocp_logs` match `(?i)(failed to unmount|unmountdevice failed|failed to detach|volume.*still attached|volumeattachment.*in use|device or resource busy)`.
   - Confirm active stage is `drain` / `pod_termination`.
3. **Execute Federated Evidence Queries**
   - Query `query_splunk_dossier` for `index=ocp_logs` and `index=k8s_objects` / KV Store; query metrics separately through Prometheus MCP.
4. **Causal Correlation & Classification**
   - Correlate failing pod to its PVC/PV and `VolumeAttachment` object on the draining node.
   - Confirm `status.attached == true` or `status.detachError != null`.
   - Traverse causal sub-tree:
     - Local CSI node daemonset pod hung (RPC DeadlineExceeded)?
     - Cloud provider / storage array lock (Multi-Attach error)?
     - Host filesystem mount busy (`device or resource busy`)?
5. **Remediation Matching**
   - Evaluate against `remediations/PLAYBOOK_CATALOG.json`.
   - If local CSI node hang $\rightarrow$ generate `playbook_restart_csi_driver` spec with validated `extra_vars`.
   - If storage array lock or busy host mount $\rightarrow$ generate targeted manual `oc` CLI fallback with safety checks.
6. **Persist & Verify**
   - Record investigation state and evidence IDs in PostgreSQL (`db/migrations/001_initial.sql`).
   - Monitor for recovery post-execution: `VolumeAttachment.status.attached == false`, pod terminates, MCO drain advances.

---

## State Model
`TRIGGERED -> CONTEXT_CAPTURED -> EVIDENCE_COLLECTED -> ROOT_CAUSE_DIAGNOSED -> REMEDIATION_MATCHED (AAP Playbook OR Manual CLI) -> PERSISTED`

---

## Data Contract
* **Investigation Record:** `investigation_id`, `cluster_id`, `node_name`, `target_namespace`, `failing_pod`, `target_pv`, `csi_driver`.
* **Evidence Citations:** `kubelet_unmount_error_log`, `volume_attachment_detach_error`, `csi_node_pod_log`.
* **Remediation Specification:**
  * If automated: `{ playbook_id: "playbook_restart_csi_driver", aap_extra_vars: { ... } }`.
  * If manual: `{ manual_cli_commands: [ ... ], safety_warnings: "...", rollback_steps: "..." }`.

---

## Guardrails
- Strictly read-only execution in the diagnostic agent.
- NEVER delete `VolumeAttachment` objects directly while a process is accessing the volume.
- NEVER force-detach a live volume without verifying host unmount state.
- Secret and credential values are stripped before persistence.
