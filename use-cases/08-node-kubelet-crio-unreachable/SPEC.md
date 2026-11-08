# SPEC: Node Becomes NotReady or Kubelet/CRI-O Unreachable

## Problem Statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **node becomes notready or kubelet/cri-o cannot finish drain**, determine whether the failure is a crashed container runtime service (CRI-O), expired Kubelet TLS certificates, or physical host hardware/power loss, and formulate an actionable remediation specification (Ansible Playbook spec or manual CLI fallback) without direct cluster mutation.

## Trigger and Scope
- Lifecycle stage: **Node Control Plane / Host Runtime / Drain**
- Trigger signal: Node condition `Ready` is `False` or `Unknown`, `kube-node-lease` is expired, or MCC reports `error draining node ...: node is not ready`.
- In scope: Read-only evidence gathering from unified Splunk multi-index search/KV store, causal classification, confidence reporting, remediation plan matching (`PLAYBOOK_CATALOG.json`), and recovery verification.
- Out of scope: Force-deleting pods on unverified hosts, force-deleting nodes, or initiating host power operations without out-of-band validation.

## Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Host systemd journal logs (crio.service, kubelet.service), MCC drain logs.
* `index=k8s_objects` / KV Store:
  * `Node` (`status.conditions` where `type == "Ready"`, `spec.unschedulable`, `metadata.annotations`).
  * `Lease` in `kube-node-lease` (`spec.renewTime`, `spec.holderIdentity`).
  * `Event` (`reason == "NodeNotReady"`, `FailedKillPod`, `NodeHasDiskPressure`).
* `index=ocp_metrics`: `up{job="kubelet"}`, `kube_node_status_condition{condition="Ready"}`.

## Diagnostic Strategy
1. **Perception:** Ingest unified Splunk dossier in a single round-trip.
2. **Correlation:** Match MCC error node to `Node` condition and verify `kube-node-lease` freshness.
3. **Causal Depth:** Determine *why* the node is unreachable:
   - Is `crio.service` in a failed state while host kernel and network are alive? (Branch 3A).
   - Is Kubelet client TLS certificate expired or CSR pending approval? (Branch 3B).
   - Is the host completely silent (power loss, kernel panic, or hypervisor crash)? (Branch 3C).

## Two-Tier Remediation Contract
1. **Playbook Matching (AAP / AWX):**
   - If CRI-O service crashed on an accessible, cordoned host:
     - Match `playbook_restart_failed_systemd_unit` from `remediations/PLAYBOOK_CATALOG.json`.
     - Generate `aap_extra_vars`: `{ target_cluster, target_node, systemd_service_name: "crio" }`.
     - Risk level: `medium`. Requires human approval.
2. **Targeted CLI Fallback (Human SRE Runbook):**
   - If Kubelet TLS cert expired: generate CSR verification and approval commands (`oc adm certificate approve`).
   - If host hardware/power lost: generate out-of-band IPMI / hypervisor console inspection runbook.

## Safety Constraints
* NEVER force-delete pods (`--force --grace-period=0`) on a NotReady node without physical power-off / fencing verification. Partitioned hosts will corrupt shared SAN/CSI storage.
* NEVER reboot or restart services on an uncordoned node.
* The agent has zero direct mutation tools.

## Success Criteria
Node condition `Ready` returns to `True`, node lease is freshly renewed within 40 seconds, and MCC resumes drain or MCD continues configuration rollout.

---

## Agent Graph Integration Contract

This use case is invoked by the shared 10-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`.

### Bounded Execution
* Investigation Deadline: 45 seconds.
* Tool Budget: Max 2 Splunk tool calls per investigation.
* Output: Structured report with evidence citations and either an `aap_launch_spec` or `manual_cli_fallback`.
