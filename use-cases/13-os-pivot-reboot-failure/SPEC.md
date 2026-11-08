# SPEC: OS Pivot, Reboot or Post-Reboot Verification Failure

## Problem Statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **OS pivot, reboot or post-reboot verification failure**, isolate whether the breakdown occurred during pre-reboot `rpm-ostree` image staging (e.g. `/boot` disk full), during host reboot (firmware/GRUB/kernel hang), or post-reboot verification (Greenboot auto-rollback or commit mismatch), and formulate an actionable remediation specification (manual CLI fallback) without direct cluster mutation.

## Trigger and Scope
- Lifecycle stage: **Apply / OS Pivot / Reboot / Verification**
- Trigger signal: MCD logs match `(?i)(failed to pivot|rpm-ostree.*failed|reboot.*failed|booted deployment.*does not match|failed to verify booted|node has not rebooted)` OR Node condition `Ready` is `Unknown` past the reboot grace window (> 15m) OR Node annotation `state` is `Degraded` with reason `FailedToVerifyBootedDeployment`.
- In scope: Read-only evidence gathering from unified Splunk multi-index search/KV store, distinguishing pre-reboot, reboot-hang, and post-reboot verification phases, confidence reporting, safe manual CLI fallback runbook generation, and recovery verification.
- Out of scope: Autonomous node power cycling or reboots, force-deleting nodes, or modifying GRUB configurations directly from the agent.

## Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Daemon pivot logs, host systemd journal logs, Kubelet logs.
* `index=k8s_objects` / KV Store:
  * `Node` (`status.conditions` where `type == "Ready"`, `metadata.annotations['machineconfiguration.openshift.io/state']`, `currentConfig`, `desiredConfig`).
  * `Lease` in `kube-node-lease` (`spec.renewTime`).
  * `MachineConfigPool` (`status.configuration`, `status.updatedMachineCount`).
  * `Event` (node reboot and condition events).
* `index=ocp_metrics`: `up{job="kubelet"}`, `machine_config_daemon_state`.

## Diagnostic Strategy
1. **Perception:** Ingest unified Splunk dossier in a single round-trip.
2. **Correlation:** Check Node `currentConfig` vs `desiredConfig`, `kube-node-lease` age, and MCD pivot logs.
3. **Causal Depth:** Determine the exact failure point:
   - Did `rpm-ostree rebase` fail before reboot due to `/boot` space exhaustion or image pull failure? (Branch 3A).
   - Did the host reboot command execute, but the host never came back up (> 15m silence)? (Branch 3B).
   - Did the host reboot, but Greenboot rolled back to the old deployment due to a critical boot service failure? (Branch 3C).

## Two-Tier Remediation Contract
1. **Playbook Matching (AAP / AWX):**
   - **Automated remediation is STRICTLY PROHIBITED** (`matched: false`). Operating system pivots and kernel deployments require hardware and console validation; uncoordinated power actions risk corrupting the GRUB partition.
2. **Targeted CLI Fallback (Human SRE Runbook):**
   - For pre-reboot staging: output `rpm-ostree cleanup -m` commands to free space in `/boot`.
   - For reboot hangs: output out-of-band IPMI / virtual console troubleshooting runbook.
   - For post-reboot rollbacks: output Greenboot log inspection and ostree deployment status commands.

## Safety Constraints
* NEVER initiate reboots or power resets autonomously.
* NEVER delete Node objects in Kubernetes while host is offline.
* The agent has zero direct mutation tools.

## Success Criteria
Node condition `Ready` is restored, `node.metadata.annotations['machineconfiguration.openshift.io/currentConfig'] == node.metadata.annotations['machineconfiguration.openshift.io/desiredConfig']`, Node annotation `state` becomes `Done`, and MachineConfigPool updated count advances.

---

## Agent Graph Integration Contract

This use case is invoked by the shared 10-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`.

### Bounded Execution
* Investigation Deadline: 45 seconds.
* Tool Budget: Max 2 Splunk tool calls per investigation.
* Output: Structured report with evidence citations and either an `aap_launch_spec` or `manual_cli_fallback`.
