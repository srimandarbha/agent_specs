# SPEC: Drain Annotation or Uncordon Coordination Mismatch

## Problem Statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by a **drain completion annotation or uncordon coordination mismatch**, determine whether the root cause is external competing automation uncordoning the node prematurely, an API optimistic locking collision (`409 Conflict`) dropping `lastAppliedDrain`, or an invalid completion state, and formulate an actionable remediation specification (Ansible Playbook spec or manual CLI fallback) without direct cluster mutation.

## Trigger and Scope
- Lifecycle stage: **Drain Controller Coordination / Uncordon**
- Trigger signal: MCC/MCD logs match `(?i)(uncordon.*during update|desiredDrain.*lastAppliedDrain|drain.*mismatch|node.*unexpectedly schedulable|waiting for drain.*annotation)` OR node annotations `desiredDrain` and `lastAppliedDrain` diverge while 0 drainable pods remain.
- In scope: Read-only evidence gathering from unified Splunk multi-index search/KV store, causal classification, confidence reporting, remediation plan matching (`PLAYBOOK_CATALOG.json`), and recovery verification.
- Out of scope: Autonomous cluster mutation, forging completion annotations while workloads are active, or uncordoning nodes mid-update.

## Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Controller logs, Machine Config Daemon logs, and API server audit logs.
* `index=k8s_objects` / KV Store:
  * `Node` (`spec.unschedulable`, `metadata.annotations['machineconfiguration.openshift.io/desiredDrain']`, `metadata.annotations['machineconfiguration.openshift.io/lastAppliedDrain']`, `resourceVersion`).
  * `Pod` (`spec.nodeName`, creation timestamps, phase).
  * `MachineConfigPool` (`status.phase`, `status.updatedMachineConfig`, `spec.paused`).
  * `Event` (involvedObject.kind == "Node", cordon/uncordon events).
* `index=ocp_metrics`: `machine_config_pool_status_updating`, `machine_config_daemon_state`.

## Diagnostic Strategy
1. **Perception:** Ingest unified Splunk dossier in a single round-trip.
2. **Correlation:** Check `spec.unschedulable` and compare `desiredDrain` with `lastAppliedDrain` on the target Node.
3. **Causal Depth:** Determine *why* coordination is broken:
   - Was the node uncordoned prematurely by external automation or an administrator while MCO was updating?
   - Did MCC successfully drain all pods (0 drainable pods remaining) but fail to persist `lastAppliedDrain` due to API 409 conflict?
   - Is drain still actively running with real pods blocked on eviction or storage? (Handoff to `01`, `03`, or `04`).

## Two-Tier Remediation Contract
1. **Playbook Matching (AAP / AWX):**
   - If external uncordon detected (Branch 3A) or annotation desync with 0 pods (Branch 3B):
     - Match `playbook_reconcile_drain_annotation` from `remediations/PLAYBOOK_CATALOG.json`.
     - Generate `aap_extra_vars`: `{ target_cluster, draining_node, expected_mco_drain_state, action: "reconcile_and_cordon" }`.
     - Risk level: `low`. Requires human approval.
2. **Targeted CLI Fallback (Human SRE Runbook):**
   - If competing automation cannot be disabled automatically or live workloads run on a node with forged completion annotations:
     - Set `playbook_match: null`.
     - Generate manual `oc` commands to immediately re-cordon, audit competing controllers, and safely re-invoke drain.

## Safety Constraints
* NEVER forge `lastAppliedDrain` if non-daemonset pods are actively running on the node.
* NEVER uncordon a node while MachineConfigDaemon is mid-apply or reboot.
* The agent has zero direct mutation tools.

## Success Criteria
`desiredDrain` equals `lastAppliedDrain`, `spec.unschedulable` remains `true` throughout the node maintenance window, and MCD advances to configuration application and reboot.

---

## Agent Graph Integration Contract

This use case is invoked by the shared 10-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`.

### Bounded Execution
* Investigation Deadline: 45 seconds.
* Tool Budget: Max 2 Splunk tool calls per investigation.
* Output: Structured report with evidence citations and either an `aap_launch_spec` or `manual_cli_fallback`.
