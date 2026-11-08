# SPEC: Machine Config Daemon Configuration Drift

## Problem Statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **Machine Config Daemon reports configuration drift**, determine whether the drift is caused by a failed auxiliary systemd service, out-of-band manual modification of an MCO-managed configuration file in `/etc`, or immutable OS filesystem corruption, and formulate an actionable remediation specification (Ansible Playbook spec or manual CLI fallback) without direct cluster mutation.

## Trigger and Scope
- Lifecycle stage: **MCD Preflight Verification / Configuration Apply**
- Trigger signal: Node annotation `machineconfiguration.openshift.io/state` is `Degraded`, MCD logs match `(?i)(content of file.*does not match expected|unexpected file mode|config drift detected)`, or Prometheus metric `machine_config_daemon_state{state="Degraded"} == 1`.
- In scope: Read-only evidence gathering from unified Splunk multi-index search/KV store, correlation with current/desired MachineConfig metadata, remediation plan matching (`PLAYBOOK_CATALOG.json`), and recovery verification.
- Out of scope: Editing host files autonomously, unapproved creation of MCD forcefile (`/run/machine-config-daemon-force`), or modifying immutable OS binaries.

## Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Daemon pod logs, host systemd journal logs.
* `index=k8s_objects` / KV Store:
  * `Node` (`metadata.annotations['machineconfiguration.openshift.io/state']`, `machineconfiguration.openshift.io/reason`, `currentConfig`, `desiredConfig`).
  * `MachineConfigPool` (`status.conditions` where `type == "Degraded"`, `status.configuration`).
  * `Event` (node Degraded condition events).
* `index=ocp_metrics`: `machine_config_daemon_state{state="Degraded"}`.

## Diagnostic Strategy
1. **Perception:** Ingest unified Splunk dossier in a single round-trip.
2. **Correlation:** Extract drifted node and file path from MCD log and verify against Node Degraded state in KV Store.
3. **Causal Depth:** Determine *what* drifted and *why*:
   - Is it a failed auxiliary systemd unit on an otherwise healthy host? (Branch 3A).
   - Is it an on-disk `/etc` configuration file altered by manual administrative edits or external agents? (Branch 3B).
   - Is it an immutable ostree filesystem corruption? (Branch 3C).

## Two-Tier Remediation Contract
1. **Playbook Matching (AAP / AWX):**
   - If drift is isolated to an allowlisted failed systemd unit:
     - Match `playbook_restart_failed_systemd_unit` from `remediations/PLAYBOOK_CATALOG.json`.
     - Generate `aap_extra_vars`: `{ target_cluster, target_node, systemd_service_name }`.
     - Risk level: `medium`. Requires human approval.
2. **Targeted CLI Fallback (Human SRE Runbook):**
   - For managed file drift in `/etc`: generate inspection commands (`cat <file>`, `oc get mc <desired>`) and provide instructions for manual revert or controlled forcefile trigger (`touch /run/machine-config-daemon-force`).

## Safety Constraints
* NEVER create `/run/machine-config-daemon-force` autonomously (triggers immediate overwrite and potential host reboot).
* NEVER edit host files directly from the agent.
* The agent has zero direct mutation tools.

## Success Criteria
Node annotation `machineconfiguration.openshift.io/state` returns to `Done`, MCP condition `Degraded` becomes `False`, and MCD preflight verification passes cleanly.

---

## Agent Graph Integration Contract

This use case is invoked by the shared 10-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`.

### Bounded Execution
* Investigation Deadline: 45 seconds.
* Tool Budget: Max 2 Splunk tool calls per investigation.
* Output: Structured report with evidence citations and either an `aap_launch_spec` or `manual_cli_fallback`.
