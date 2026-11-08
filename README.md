# MCO drain and MCP-stuck troubleshooting use-case pack

This is an evidence-driven design pack for an OpenShift SRE diagnostic agent. It contains **16 use cases**, each with five dedicated documents:

- `SPEC.md`: trigger, scope, evidence contract, acceptance criteria and safety requirements.
- `design.md`: diagnosis logic, evidence ordering, state model and decision paths.
- `plan.md`: implementation phases, tasks, test coverage and rollout gates.
- `skill.md`: agent-operational instructions, read-only commands, interpretation and escalation.
- `eval.md`: offline evaluation test matrix, golden fixtures, scoring rubrics, and prohibited failure modes.

## Use cases

- `01-pdb-eviction-blocked`: PodDisruptionBudget blocks eviction
- `02-webhook-admission-failure`: Admission webhook blocks pod deletion or eviction
- `03-pod-termination-finalizer`: Pod remains Terminating or finalizer cleanup stalls
- `04-storage-unmount-detach`: Storage unmount or detach stalls pod termination
- `05-ocv-vm-not-migratable`: OpenShift Virtualization VM is not live-migratable
- `06-ocv-stale-virt-launcher`: Stale source virt-launcher pod after completed migration
- `07-reschedule-capacity-affinity`: Replacement workloads cannot schedule after eviction
- `08-node-kubelet-crio-unreachable`: Node becomes NotReady or kubelet/CRI-O cannot finish drain
- `09-api-etcd-latency`: API server or etcd latency prevents drain progress
- `10-mcp-paused-or-coordination`: MCP paused or rollout coordination prevents progress
- `11-config-drift-mcd-degraded`: Machine Config Daemon reports configuration drift
- `12-mcd-config-render-apply`: Rendered MachineConfig or configuration application failure
- `13-os-pivot-reboot-failure`: OS pivot, reboot or post-reboot verification fails
- `14-uncordon-or-drainer-annotation`: Drain completion annotation or uncordon coordination mismatch
- `15-disk-pressure-host-resource`: Node disk pressure or host resource exhaustion stalls cleanup/update
- `16-csi-max-volume-limit-exceeded`: CSI driver maximum volume capacity reached on candidate nodes (MAX_VOLUMES_PER_NODE)

## Operating principles

1. Diagnose lifecycle stage first: drain, config apply, reboot/verification, uncordon, MCP rollout, or broader ClusterVersion/ClusterOperator gate.
2. Treat MCC logs naming a pod as the primary starting evidence for a drain failure. A generic MCP `Updating` status is not enough to conclude drain is blocked.
3. Start read-only. Do not automatically patch PDBs, delete webhooks, clear finalizers, force-delete pods, detach storage, change VM eviction strategy, alter MCP pause/maxUnavailable, or reboot nodes.
4. Distinguish facts from hypotheses. Report evidence timestamps, commands and output excerpts; state confidence and missing evidence.
5. Never treat `oc delete pod --force --grace-period=0` as a harmless restart. It removes the API object without proving the process stopped on an unreachable node.
6. Use version-matched runbooks and source. `main` may differ from the cluster's shipped MCO.
7. The agent operates in a read-only diagnostic mode and maps remediations to either an approved Ansible Playbook or an exact manual `oc` CLI fallback runbook.

## Enhanced agent design & Architecture

The pack utilizes a deterministic 10-node LangGraph design optimized for low-latency multi-cluster diagnostics:

### Selected operating decisions
- **Trigger:** Alert-driven (`MachineConfigControllerDrainError`) and engineer-triggered.
- **Evidence Pipeline:** Unified Splunk Multi-Index Search (`index=ocp_logs`, `index=k8s_objects` / KV Store, `index=ocp_metrics`) executing in a single round-trip (< 10 seconds).
- **Data Minimization (Golden Six):** Object collection in OpenTelemetry is restricted to `Pod`, `PodDisruptionBudget`, `Node`, `VolumeAttachment`, `MachineConfigPool`, and `Event`, with `metadata.managedFields` stripped to prevent OOMKills.
- **Remediation Model:** Two-tier handoff via [`remediations/PLAYBOOK_CATALOG.json`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/remediations/PLAYBOOK_CATALOG.json). Clean matches generate Ansible Automation Platform (AAP / AWX) execution specs. Unmatched or high-risk cases generate precise manual `oc` CLI runbooks with safety guardrails.
- **Memory:** SQL-based episodic/curated memory in PostgreSQL (`db/migrations/001_initial.sql`).
- **First vertical slice:** `01-pdb-eviction-blocked`.

### Key System Files
- `intent.md`: High-level architectural intent and design decisions.
- `architecture/LANGGRAPH_DESIGN.md`: Node state, edges, budgets, and safety policy.
- `contracts/TOOL_CONTRACTS.md`: Multi-index SPL and KV Store contracts, AAP remediation specs.
- `remediations/PLAYBOOK_CATALOG.json`: Catalog of approved Ansible Playbooks and variable schemas.
- `docs/OBSERVABILITY_REQUIREMENTS.md`: Streamlined Golden Six allowlist and OTel configuration.
- `db/migrations/001_initial.sql`: PostgreSQL schema for incident memory and recommendations.
- `tests/TEST_STRATEGY.md`: Acceptance, security, and integration testing gates.
- `tests/EVALUATION_FRAMEWORK.md`: 4-tier continuous evaluation framework and CI/CD quality gates.
