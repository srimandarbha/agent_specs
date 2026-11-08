# SPEC: PodDisruptionBudget Blocks Eviction

## Problem Statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **PodDisruptionBudget blocks eviction**, determine *why* the disruption budget is exhausted, and formulate an actionable resolution (Ansible Playbook spec or manual CLI fallback) using evidence from Splunk without direct Kubernetes cluster mutation.

## Trigger and Scope
- Lifecycle stage: **Drain / Eviction**
- Trigger signal: MCC log contains `Cannot evict pod ... as it would violate the pod's disruption budget` or equivalent eviction-subresource denial.
- In scope: Read-only evidence gathering from unified Splunk multi-index search/KV store, causal classification, confidence reporting, remediation plan matching (`PLAYBOOK_CATALOG.json`), and recovery verification.
- Out of scope: Autonomous direct API mutation without approval, force-deleting pods, or blindly weakening PDBs to zero.

## Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: MCC drain log naming namespace, pod, and eviction denial string.
* `index=k8s_objects` / KV Store:
  * `Pod` (`metadata.labels`, `metadata.ownerReferences`, phase, conditions).
  * `PodDisruptionBudget` (`spec.selector`, `spec.minAvailable`, `status.disruptionsAllowed`, `status.currentHealthy`, `status.desiredHealthy`).
* `index=ocp_metrics`: `kube_pod_disruption_budget_status_pod_disruptions_allowed`, `kube_pod_container_status_waiting_reason`.

## Diagnostic Strategy
1. **Perception:** Ingest unified Splunk dossier in a single round-trip.
2. **Correlation:** Match MCC log error pod to PDB label selector within the same namespace.
3. **Causal Depth:** Determine *why* `disruptionsAllowed == 0`:
   - Single-replica workload with `minAvailable: 1` or `maxUnavailable: 0`?
   - Sibling replica crashing or unready (`CrashLoopBackOff`, `ContainersNotReady`)?
   - Cluster capacity exhausted preventing replacement pod scheduling?

## Two-Tier Remediation Contract
1. **Playbook Matching (AAP / AWX):**
   - If workload is a multi-replica Deployment/StatefulSet, cluster capacity exists, and scaling +1 replica will satisfy PDB:
     - Match `playbook_pdb_scale_up` from `remediations/PLAYBOOK_CATALOG.json`.
     - Generate `aap_extra_vars`: `{ target_cluster, target_namespace, workload_kind, workload_name, target_pdb_name, current_replicas, scale_to }`.
     - Risk level: `low`. Requires approval before execution.
2. **Targeted CLI Fallback (Human SRE Runbook):**
   - If single-replica, unmanaged pod, or capacity-constrained:
     - Set `playbook_match: null`.
     - Generate exact, copy-pasteable `oc` commands:
       ```bash
       oc get pods -n <namespace> -l <selector>
       oc describe pdb <pdb> -n <namespace>
       oc scale deployment <deployment> -n <namespace> --replicas=<N+1>
       ```

## Safety Constraints
* Never patch `minAvailable` to 0 without workload-owner approval.
* Never execute `oc delete pod --force --grace-period=0`.
* The agent has zero direct mutation tools.

## Success Criteria
MCC logs show the blocker pod evicted, desired and last-applied drainer annotations converge, node update progresses, and original PDB policy remains satisfied.

---

## Agent Graph Integration Contract

This use case is invoked by the shared 10-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`. 

### Bounded Execution
* Investigation Deadline: 45 seconds.
* Tool Budget: Max 2 Splunk tool calls per investigation.
* Output: Structured report with evidence citations and either an `aap_launch_spec` or `manual_cli_fallback`.
