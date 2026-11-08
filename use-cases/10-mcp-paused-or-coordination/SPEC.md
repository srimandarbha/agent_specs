# SPEC: MachineConfigPool Paused or Rollout Coordination Prevents Progress

## Problem Statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **mcp paused or rollout coordination prevents progress**, determine whether the pause is a stale maintenance hold, an expected concurrency limit serialization, or a safety interlock due to a degraded configuration, and formulate an actionable remediation specification (Ansible Playbook spec or manual CLI fallback) without direct cluster mutation.

## Trigger and Scope
- Lifecycle stage: **MCP Rollout Coordination / Pool Maintenance**
- Trigger signal: Target MachineConfigPool has `spec.paused == true`, MCC logs report `pool is paused, not updating`, or Prometheus metric `machine_config_pool_status_paused == 1`.
- In scope: Read-only evidence gathering from unified Splunk multi-index search/KV store, verification of pool conditions and node health, remediation plan matching (`PLAYBOOK_CATALOG.json`), and recovery verification.
- Out of scope: Unpausing degraded pools, raising `maxUnavailable` without cluster capacity validation, or mutating MachineConfigs.

## Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Controller rollout logs, Machine Config Daemon logs.
* `index=k8s_objects` / KV Store:
  * `MachineConfigPool` (`spec.paused`, `spec.maxUnavailable`, `status.configuration`, `status.conditions`, `status.machineCount`, `status.readyMachineCount`, `status.unavailableMachineCount`).
  * `Node` (`status.conditions` where `type == "Ready"`, `spec.unschedulable`).
  * `Event` (MCP paused/unpaused events).
* `index=ocp_metrics`: `machine_config_pool_status_paused`, `machine_config_pool_status_updating`, `machine_config_pool_status_degraded`.

## Diagnostic Strategy
1. **Perception:** Ingest unified Splunk dossier in a single round-trip.
2. **Correlation:** Match alert to `MachineConfigPool` in KV Store and check `spec.paused`.
3. **Causal Depth:** Determine whether the pool can be safely unpaused:
   - If `spec.paused == false`: Is `unavailableMachineCount >= maxUnavailable`? (Normal serialization - Branch 3B).
   - If `spec.paused == true`:
     - Is the pool Degraded? (Branch 3C - Safety Interlock; do NOT unpause).
     - Are all existing nodes healthy and ready? (Branch 3A - Clean stale pause; safe to unpause).

## Two-Tier Remediation Contract
1. **Playbook Matching (AAP / AWX):**
   - If pool is paused, healthy, not degraded, and ready for rollout:
     - Match `playbook_unpause_mcp` from `remediations/PLAYBOOK_CATALOG.json`.
     - Generate `aap_extra_vars`: `{ target_cluster, target_mcp_name }`.
     - Risk level: `medium`. Requires human approval.
2. **Targeted CLI Fallback (Human SRE Runbook):**
   - If pool is Degraded or contains failing nodes:
     - Set `playbook_match: null`.
     - Generate manual `oc describe mcp` and controller log inspection commands to resolve root cause before unpausing.

## Safety Constraints
* NEVER unpause a `Degraded` MachineConfigPool (cascading failure risk).
* NEVER unpause a pool if existing nodes in the pool report `NotReady`.
* The agent has zero direct mutation tools.

## Success Criteria
`mcp.spec.paused` becomes `false`, `status.conditions[?(@.type=="Updating")].status == "True"`, and rollout progresses within `maxUnavailable` limits.

---

## Agent Graph Integration Contract

This use case is invoked by the shared 10-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`.

### Bounded Execution
* Investigation Deadline: 45 seconds.
* Tool Budget: Max 2 Splunk tool calls per investigation.
* Output: Structured report with evidence citations and either an `aap_launch_spec` or `manual_cli_fallback`.
