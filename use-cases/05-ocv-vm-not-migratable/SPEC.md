# SPEC: OpenShift Virtualization VM Is Not Live-Migratable

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Problem Statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **OpenShift Virtualization VM is not live-migratable**, isolate whether the migration blocker is non-shared local storage, host PCI/GPU hardware binding, or destination node capacity exhaustion, and formulate an actionable remediation specification (manual CLI fallback with workload-owner sign-off) without direct cluster mutation.

## Trigger and Scope
- Lifecycle stage: **OCV Eviction Interceptor / Node Drain**
- Trigger signal: MCC eviction log reports `virt-launcher-eviction-interceptor.kubevirt.io` denial: `(?i)(is not live-migratable|cannot migrate vmi|VMI is configured with an eviction strategy but is not live-migratable)` OR Prometheus metric `kubevirt_vmi_non_evictable > 0`.
- In scope: Read-only evidence gathering from unified Splunk multi-index search/KV store, Prometheus OCV metric correlation, causal classification, confidence reporting, safe manual CLI fallback runbook generation, and recovery verification.
- Out of scope: Autonomous VM policy modification (`evictionStrategy: None`), unapproved guest shutdowns (`virtctl stop`), or force-deleting launcher pods.

## Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Controller eviction logs, virt-handler migration interceptor logs.
* `index=k8s_objects` / KV Store:
  * `Pod` (`metadata.labels['kubevirt.io'] == 'virt-launcher'`, `metadata.labels['vm.kubevirt.io/name']`, `spec.nodeName`, `spec.volumes`).
  * `Node` (`metadata.name`, cordon status `spec.unschedulable`).
  * `Event` (eviction interceptor denials, scheduling failures).
* `index=ocp_metrics`: `kubevirt_vmi_non_evictable{reason=~".*"}`, `kubevirt_vmi_migration_status`.

## Diagnostic Strategy
1. **Perception:** Ingest unified Splunk dossier in a single round-trip.
2. **Correlation:** Extract VM name from `virt-launcher` pod and correlate with Prometheus `kubevirt_vmi_non_evictable`.
3. **Causal Depth:** Determine *why* live migration is blocked:
   - Is it non-shared storage (`reason="DisksNotMigratable"`)? (Branch 3A).
   - Is it host PCI/GPU hardware passthrough (`reason="HostDevicesNotMigratable"`)? (Branch 3B).
   - Is it destination node scheduling deadlock / capacity starvation? (Branch 3C).

## Two-Tier Remediation Contract
1. **Playbook Matching (AAP / AWX):**
   - **Automated remediation is STRICTLY PROHIBITED** by policy (`matched: false`). Forcing VM shutdown or altering eviction policy without customer consent risks guest filesystem corruption and application downtime.
2. **Targeted CLI Fallback (Human SRE Runbook):**
   - For non-shared storage: generate commands to inspect disk bindings, plan controlled guest shutdown (`virtctl stop <vm>`), or migrate PVC to shared storage.
   - For host devices / GPU: generate maintenance window runbook to stop, allow drain, and restart post-upgrade.

## Safety Constraints
* NEVER patch `spec.template.spec.evictionStrategy` to `None` without workload-owner authorization.
* NEVER stop or restart customer VMs autonomously.
* The agent has zero direct mutation tools.

## Success Criteria
The `virt-launcher` pod terminates from the draining node (via controlled shutdown or successful migration), and MCC logs record the node drain resuming.

---

## Agent Graph Integration Contract

This use case is invoked by the shared 10-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`.

### Bounded Execution
* Investigation Deadline: 45 seconds.
* Tool Budget: Max 2 Splunk tool calls per investigation.
* Output: Structured report with evidence citations and either an `aap_launch_spec` or `manual_cli_fallback`.
