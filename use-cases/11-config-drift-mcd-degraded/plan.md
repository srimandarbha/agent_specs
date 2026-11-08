# Implementation Plan: Machine Config Daemon Configuration Drift

## Phase 0: Ground Truth & Telemetry Alignment
- [ ] Pin supported OpenShift release(s) and obtain matching MCO source/runbook revision.
- [ ] Align trigger signals in Splunk: Node annotation `state == "Degraded"` or MCD logs report `content of file ... does not match expected`.
- [ ] Confirm `index=ocp_logs`, `index=k8s_objects` (with `managedFields` stripped), and `index=ocp_metrics` (`machine_config_daemon_state`) are populated.
- [ ] Verify that `Node` and `MachineConfigPool` objects are cached in the Splunk KV Store (`k8s_live_inventory_lookup`) for instant retrieval.

## Phase 1: Read-Only Evidence Tooling
- [ ] Implement the parameterized **Unified Multi-Index Splunk Search** (`query_unified_splunk_dossier`).
- [ ] Bound search time: `earliest=-1h latest=now` for logs/metrics; `earliest=-24h` for objects (or instant KV Store lookup).
- [ ] Normalize timestamps, cluster ID, node identity, and drifted file paths into structured state.
- [ ] Redact secrets, authorization headers, and environment variables.

## Phase 2: Causal Reasoning & Classification
- [ ] Extract target node, drifted path, and reason from MCD logs.
- [ ] Verify Node `state: Degraded` annotation in KV Store.
- [ ] **Multi-level Root Cause Analysis:**
  - Has an allowlisted systemd unit failed during verification?
  - Has an `/etc` configuration file drifted due to manual administrative edits?
  - Is there underlying filesystem or ostree image corruption?

## Phase 3: Two-Tier Remediation & Playbook Matching
- [ ] **Catalog Matching:** Evaluate against [`remediations/PLAYBOOK_CATALOG.json`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/remediations/PLAYBOOK_CATALOG.json):
  - If allowlisted systemd unit failure is isolated:
    - Match `playbook_restart_failed_systemd_unit`.
    - Generate `aap_extra_vars`: `{ target_cluster, target_node, systemd_service_name }`.
    - Mark risk as `medium` and require human approval before execution.
- [ ] **Intelligent CLI Fallback:** If managed file drift in `/etc` is identified:
  - Explicitly set `playbook_match: null`.
  - Output targeted manual `oc` CLI runbook:
    ```bash
    # 1. Compare host file with authoritative MachineConfig
    oc debug node/<node> -- chroot /host cat <drifted_filepath>
    oc get mc <desired_config> -o json | jq '.spec.config.storage.files[] | select(.path=="<drifted_filepath>")'
    # 2. Trigger MCO force-reapply after human verification
    oc debug node/<node> -- chroot /host touch /run/machine-config-daemon-force
    ```
- [ ] Keep all mutation tools disabled inside the agent; hand off execution to AAP or human SRE.

## Phase 4: Verification & Acceptance Tests
- [ ] Unit tests: matching trigger, non-matching trigger, incomplete evidence, and contradictory evidence.
- [ ] Graph test: single multi-index query completes within 10s; graph completes within 45s deadline.
- [ ] Playbook matching test: failed unit produces exact `aap_extra_vars` matching schema.
- [ ] Fallback test: file drift correctly outputs diff inspection and forcefile runbook.
- [ ] Safety test: verify agent refuses autonomous creation of `/run/machine-config-daemon-force`.
- [ ] Post-remediation verification: Node state returns to `Done`, MCP degraded flag clears.

---

## Observability & Graph Integration Contract

### Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Daemon pod logs, host systemd journal logs.
* `index=k8s_objects` / KV Store: `Node` (annotations, state, reason), `MachineConfigPool` (degraded condition).
* `index=ocp_metrics`: `machine_config_daemon_state{state="Degraded"}`.

### Bounded Execution
* Max 2 Splunk tool calls total per investigation.
* 15-second per-query timeout; 45-second overall investigation deadline.
* Stop as `inconclusive` if cluster identity is ambiguous or required telemetry is unavailable.
