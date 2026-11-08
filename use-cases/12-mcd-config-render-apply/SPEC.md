# SPEC: Rendered MachineConfig or Configuration Apply Failure

## Problem Statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **rendered MachineConfig or configuration application failure**, determine whether the root cause is a controller-level MachineConfig merge collision (e.g. duplicate conflicting file paths), an invalid Ignition schema, or a host-level file-write/systemd-reload failure in MCD, and formulate an actionable remediation specification (manual CLI fallback) without direct cluster mutation.

## Trigger and Scope
- Lifecycle stage: **Desired Config Render / MCD Apply**
- Trigger signal: MCC/MCD logs match `(?i)(failed to render.*machineconfig|conflicting file.*in machineconfigs|error merging machineconfigs|failed to apply update|error writing file.*ignition|failed to reload systemd)` OR MCP condition `RenderDegraded` is `True` OR Node annotation `state` is `Degraded` with reason `FailedToApply`.
- In scope: Read-only evidence gathering from unified Splunk multi-index search/KV store, distinguishing render-time from apply-time failures, identification of conflicting source MachineConfigs, confidence reporting, safe manual CLI fallback runbook generation, and recovery verification.
- Out of scope: Directly patching or deleting generated `rendered-*` MachineConfigs, editing source MachineConfigs autonomously, or rebooting nodes without human sign-off.

## Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Controller render logs, Machine Config Daemon apply logs, systemd journal logs.
* `index=k8s_objects` / KV Store:
  * `MachineConfigPool` (`status.conditions` where `type == "RenderDegraded"` or `"Degraded"`, `spec.configuration.name`, `status.configuration.name`).
  * `Node` (`metadata.annotations['machineconfiguration.openshift.io/state']`, `machineconfiguration.openshift.io/reason`, `currentConfig`, `desiredConfig`).
  * `Event` (render failure and node apply events).
* `index=ocp_metrics`: `machine_config_pool_status_degraded`, `machine_config_daemon_state`.

## Diagnostic Strategy
1. **Perception:** Ingest unified Splunk dossier in a single round-trip.
2. **Correlation:** Check MCP conditions (`RenderDegraded`, `Degraded`) and Node annotations (`state`, `reason`).
3. **Causal Depth:** Determine the exact failure point:
   - Did the render controller fail to combine source MachineConfigs due to duplicate file path collisions? (Branch 3A).
   - Did MCD fail to write files or reload systemd units on the host due to local disk exhaustion or permission errors? (Branch 3B).
   - Did a MachineConfig specify an unsupported Ignition version or malformed syntax? (Branch 3C).

## Two-Tier Remediation Contract
1. **Playbook Matching (AAP / AWX):**
   - **Automated remediation is STRICTLY PROHIBITED** (`matched: false`). MachineConfigs define low-level operating system and kernel parameters. Modifying them autonomously carries severe risk of rendering nodes unbootable.
2. **Targeted CLI Fallback (Human SRE Runbook):**
   - For render conflicts: locate the two colliding source MachineConfigs via `jq` path inspection, with instructions to reconcile the conflicting files in version-controlled GitOps repositories.
   - For host apply failures: generate host disk inspection, journal cleanup, and systemd status inspection commands.

## Safety Constraints
* NEVER edit or delete generated `rendered-<pool>-<hash>` objects directly. Edits must be made to *source* `MachineConfig` objects.
* NEVER touch host files directly from the agent.
* The agent has zero direct mutation tools.

## Success Criteria
`mcp.status.conditions[?(@.type=="RenderDegraded")].status == "False"`, a valid desired rendered MachineConfig is generated, Node annotation `state` returns to `Done`, and `currentConfig == desiredConfig`.

---

## Agent Graph Integration Contract

This use case is invoked by the shared 10-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`.

### Bounded Execution
* Investigation Deadline: 45 seconds.
* Tool Budget: Max 2 Splunk tool calls per investigation.
* Output: Structured report with evidence citations and either an `aap_launch_spec` or `manual_cli_fallback`.
