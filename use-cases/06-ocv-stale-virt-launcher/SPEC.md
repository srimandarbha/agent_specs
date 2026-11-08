# SPEC: Stale Source Virt-Launcher Pod After Completed Migration

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Problem Statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by a **stale source virt-launcher pod after completed migration**, verify that the Virtual Machine has successfully migrated and is healthy on a target node, confirm that the old pod is truly orphaned, and formulate an actionable remediation specification (Ansible Playbook spec or manual CLI fallback) without direct cluster mutation.

## Trigger and Scope
- Lifecycle stage: **OCV Pod Cleanup / Drain**
- Trigger signal: MCC log reports drain timeout waiting for pod `virt-launcher-*` to terminate on a cordoned node, or Kubelet reports repeated errors terminating the launcher pod.
- In scope: Read-only evidence gathering from unified Splunk multi-index search/KV store, verification of replacement launcher pod on target node, remediation plan matching (`PLAYBOOK_CATALOG.json`), and recovery verification.
- Out of scope: Deleting active single-instance VM launcher pods, force-deleting pods without verifying migration success, or mutating virtualization CRDs.

## Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Controller drain logs, virt-handler logs, virt-controller logs.
* `index=k8s_objects` / KV Store:
  * `Pod` (labels `kubevirt.io == "virt-launcher"`, `vm.kubevirt.io/name`, `spec.nodeName`, `status.phase`, `status.conditions`).
  * `Node` (`metadata.name`, cordon status `spec.unschedulable`).
  * `Event` (pod killing and migration events).
* `index=ocp_metrics`: `kubevirt_vmi_migration_status{status="succeeded"}`, `kubevirt_vmi_phase_count`.

## Diagnostic Strategy
1. **Perception:** Ingest unified Splunk dossier in a single round-trip.
2. **Correlation:** Extract VM name from the failing `virt-launcher` pod and locate all sibling pods with the same `vm.kubevirt.io/name` label in the namespace.
3. **Causal Depth:** Determine whether the pod is safe to clean up:
   - Does a replacement launcher pod exist on a different node in `Running` and `Ready` state?
   - Does Prometheus metric confirm `kubevirt_vmi_migration_status == Succeeded`?
   - If YES $\rightarrow$ Orphaned launcher pod confirmed (Branch 3A).
   - If NO $\rightarrow$ Live migration failed or incomplete; VM still homed on draining node (Branch 3B). Handoff to `05-ocv-vm-not-migratable`.

## Two-Tier Remediation Contract
1. **Playbook Matching (AAP / AWX):**
   - If live migration succeeded, replacement launcher is healthy on another node, and source pod is stuck:
     - Match `playbook_cleanup_stale_virt_launcher` from `remediations/PLAYBOOK_CATALOG.json`.
     - Generate `aap_extra_vars`: `{ target_cluster, vmi_namespace, vmi_name, stale_pod_name, draining_node }`.
     - Risk level: `medium`. Requires human approval.
2. **Targeted CLI Fallback (Human SRE Runbook):**
   - If dual-active process detected, migration metric missing, or storage lock held:
     - Set `playbook_match: null`.
     - Generate manual `oc` verification commands (`oc get vmi`, `oc get vmim`, `oc get pods -l vm.kubevirt.io/name`) with strict safety warnings.

## Safety Constraints
* NEVER delete a `virt-launcher` pod if it is the only launcher pod for that virtual machine.
* NEVER delete a `virt-launcher` pod without verifying the active VM is answering traffic on the target node.
* The agent has zero direct mutation tools.

## Success Criteria
The stale `virt-launcher` pod is removed from the draining node, the replacement pod on the target node remains running and healthy, and MCC drain advances.

---

## Agent Graph Integration Contract

This use case is invoked by the shared 10-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`.

### Bounded Execution
* Investigation Deadline: 45 seconds.
* Tool Budget: Max 2 Splunk tool calls per investigation.
* Output: Structured report with evidence citations and either an `aap_launch_spec` or `manual_cli_fallback`.
