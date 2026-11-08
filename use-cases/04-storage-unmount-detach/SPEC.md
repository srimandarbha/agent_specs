# SPEC: Storage Unmount or Detach Stalls Pod Termination

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Problem Statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **storage unmount or detach stalls pod termination**, isolate whether the root cause is a hung CSI node daemon, a storage array/cloud multi-attach lock, or a busy host mount point, and formulate an actionable resolution (Ansible Playbook spec or manual CLI fallback) without direct cluster mutation.

## Trigger and Scope
- Lifecycle stage: **Pod Termination / Storage Cleanup**
- Trigger signal: Pod remains Terminating; Kubelet or CSI logs in `ocp_logs` match `(?i)(failed to unmount|unmountdevice failed|failed to detach|volume.*still attached|volumeattachment.*in use|device or resource busy)`.
- In scope: Read-only evidence gathering from unified Splunk multi-index search/KV store, causal classification, remediation plan matching (`PLAYBOOK_CATALOG.json`), and recovery verification.
- Out of scope: Force-deleting VolumeAttachment objects, unapproved force-detaching live storage, or declaring health based on one signal.

## Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Kubelet unmount errors, CSI driver node/controller error logs.
* `index=k8s_objects` / KV Store:
  * `Pod` (`spec.volumes`, `metadata.deletionTimestamp`, `phase`).
  * `VolumeAttachment` (`spec.nodeName`, `spec.source.persistentVolumeName`, `status.attached`, `status.detachError`).
  * `Node` (`metadata.name`, cordon status).

## Diagnostic Strategy
1. **Perception:** Ingest unified Splunk dossier in a single round-trip.
2. **Correlation:** Correlate Kubelet unmount failure with `VolumeAttachment` on the draining node.
3. **Causal Depth:** Determine *why* detachment is stalled:
   - Local CSI node-driver daemonset hung or RPC timeout?
   - Multi-attach error / storage array lock?
   - Host mount point held open by zombie process (`device or resource busy`)?

## Two-Tier Remediation Contract
1. **Playbook Matching (AAP / AWX):**
   - If local CSI node daemonset hang (RPC timeout):
     - Match `playbook_restart_csi_driver` from `remediations/PLAYBOOK_CATALOG.json`.
     - Generate `aap_extra_vars`: `{ target_cluster, draining_node, csi_driver_namespace, csi_driver_daemonset }`.
     - Risk level: `low`. Requires human approval.
2. **Targeted CLI Fallback (Human SRE Runbook):**
   - If storage array lock (multi-attach) or busy host mount:
     - Set `playbook_match: null`.
     - Generate exact manual `oc` commands to inspect CSI controller logs, check host open file descriptors (`fuser` / `lsof`), and coordinate safe detach.

## Safety Constraints
* NEVER delete `VolumeAttachment` objects while a process is writing to disk (causes silent filesystem corruption).
* NEVER force-delete a pod with `--grace-period=0` without verifying the disk is unmounted.
* The agent has zero direct mutation tools.

## Success Criteria
VolumeAttachment `status.attached` becomes `false` or object is deleted, the old pod terminates, volume attachment state is clean, and MCO drain advances.

---

## Agent Graph Integration Contract

This use case is invoked by the shared 10-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`.

### Bounded Execution
* Investigation Deadline: 45 seconds.
* Tool Budget: Max 2 Splunk tool calls per investigation.
* Output: Structured report with evidence citations and either an `aap_launch_spec` or `manual_cli_fallback`.
