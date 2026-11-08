# SPEC: Pod Remains Terminating or Finalizer Cleanup Stalls

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Problem Statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **pod remains terminating or finalizer cleanup stalls**, determine whether the blocker is an un-reconciled operator finalizer, a storage unmount interlock, or a container runtime / CRI-O process hang, and formulate an actionable resolution without direct cluster mutation.

## Trigger and Scope
- Lifecycle stage: **Pod Termination / Deletion**
- Trigger signal: MCC reports `error when waiting for pod ... to terminate` or repeats after drain-helper timeout; pod has a persistent `metadata.deletionTimestamp`.
- In scope: Read-only evidence gathering from unified Splunk multi-index search/KV store, causal classification, confidence reporting, safe manual CLI fallback runbook generation, and recovery verification.
- Out of scope: Autonomous finalizer stripping, force-deleting pods (`--grace-period=0`), or rebooting nodes without human sign-off.

## Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: MCC drain logs, Kubelet container kill errors, and operator/controller logs.
* `index=k8s_objects` / KV Store:
  * `Pod` (`metadata.deletionTimestamp`, `metadata.finalizers`, `spec.terminationGracePeriodSeconds`, `phase`, container states).
  * `Node` (`metadata.name`, `status.conditions` where `type == "Ready"`).
  * `Event` (`reason == "FailedKillPod"`, `killing`, or finalizer-related events).
  * `VolumeAttachment` (correlated if `pvc-protection` finalizer is present).
* `index=ocp_metrics`: `kube_pod_status_phase{phase="Terminating"}`.

## Diagnostic Strategy
1. **Perception:** Ingest unified Splunk dossier in a single round-trip.
2. **Correlation:** Match MCC log error pod to `k8s_objects` / KV Store and evaluate `metadata.finalizers`.
3. **Causal Depth:** Determine *why* pod termination is blocked:
   - Are finalizers present?
     - If operator/custom finalizers: is the controlling operator pod crashed or failing reconciliation?
     - If `kubernetes.io/pvc-protection`: is the volume still attached? (Handoff to `04-storage-unmount-detach`).
   - Are finalizers empty?
     - Has `terminationGracePeriodSeconds` expired?
     - Does Kubelet report `FailedKillPod` / `KillPodSandbox` deadline exceeded due to hung `preStop` hook or kernel D-state process?

## Two-Tier Remediation Contract
1. **Playbook Matching (AAP / AWX):**
   - **Automated finalizer removal is STRICTLY PROHIBITED** by policy (`matched: false`) due to extreme risk of data corruption, split-brain volume access, or orphaned cloud infrastructure.
   - Exception: If the blocker is isolated to a storage driver hang (Branch 3B), delegate to `playbook_restart_csi_driver`.
2. **Targeted CLI Fallback (Human SRE Runbook):**
   - For stalled operator finalizers: generate safe inspection commands for the owning controller, instructions to restart crashed operators, and conditional, human-gated finalizer removal commands.
   - For hung container processes: generate node debug session commands (`crictl ps`, `crictl stopp`, and CRI-O restart commands) under cordoned node conditions.

## Safety Constraints
* NEVER patch `metadata.finalizers` to empty autonomously.
* NEVER execute `oc delete pod --force --grace-period=0` without verifying external storage and process termination.
* The agent has zero direct mutation tools.

## Success Criteria
The blocker pod record disappears from cluster inventory (`k8s_objects` / KV Store), no new `FailedKillPod` events are emitted, and MCC logs record the node drain resuming or completing.

---

## Agent Graph Integration Contract

This use case is invoked by the shared 10-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`.

### Bounded Execution
* Investigation Deadline: 45 seconds.
* Tool Budget: Max 2 Splunk tool calls per investigation.
* Output: Structured report with evidence citations and either an `aap_launch_spec` or `manual_cli_fallback`.
