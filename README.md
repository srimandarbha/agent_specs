# MCO drain and MCP-stuck troubleshooting use-case pack

This is an evidence-driven design pack for an OpenShift SRE diagnostic agent. It contains **15 use cases**, each with four dedicated documents:

- `SPEC.md`: trigger, scope, evidence contract, acceptance criteria and safety requirements.
- `design.md`: diagnosis logic, evidence ordering, state model and decision paths.
- `plan.md`: implementation phases, tasks, test coverage and rollout gates.
- `skill.md`: agent-operational instructions, read-only commands, interpretation and escalation.

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

## Operating principles

1. Diagnose lifecycle stage first: drain, config apply, reboot/verification, uncordon, MCP rollout, or broader ClusterVersion/ClusterOperator gate.
2. Treat MCC logs naming a pod as the primary starting evidence for a drain failure. A generic MCP `Updating` status is not enough to conclude drain is blocked.
3. Start read-only. Do not automatically patch PDBs, delete webhooks, clear finalizers, force-delete pods, detach storage, change VM eviction strategy, alter MCP pause/maxUnavailable, or reboot nodes.
4. Distinguish facts from hypotheses. Report evidence timestamps, commands and output excerpts; state confidence and missing evidence.
5. Never treat `oc delete pod --force --grace-period=0` as a harmless restart. It removes the API object without proving the process stopped on an unreachable node.
6. Use version-matched runbooks and source. `main` may differ from the cluster's shipped MCO.
7. The agent recommends actions; disruptive remediation requires human approval and a recorded rollback/verification plan.

## Suggested pack layout

```text
mco-drain-troubleshooting-pack/
  README.md
  SOURCE_REVIEW.md
  use-cases/
    01-pdb-eviction-blocked/
      SPEC.md
      design.md
      plan.md
      skill.md
    ...
```

## Important source nuance

The current upstream drain controller's `Force: true` config is part of the Kubernetes drain helper configuration and must not be interpreted as permission to force-delete any arbitrary pod from the API. The code uses the desired-drainer and last-applied-drainer annotations as a coordination contract. If an external actor uncordons a node during drain, the controller intentionally avoids recording successful completion because workloads might have rescheduled onto it.


## Enhanced agent design (2026-11-03)

The pack now includes a shared 12-node LangGraph design, conditional routing/exit conditions, bounded retries and deadlines, tool contracts for Splunk MCP / Prometheus MCP and a separate Kubernetes object collector, a PostgreSQL migration, and a test strategy. All 15 use cases have graph integration contracts and case-specific diagnosis gates. The first vertical slice is PDB/eviction blocked.

### Selected operating decisions
- Trigger: alert-driven and engineer-triggered.
- Evidence: Splunk container logs + normalized Kubernetes object snapshots/changes/Events from a separate read-only collector + Prometheus metrics. The agent itself has only Splunk MCP and Prometheus MCP.
- Operating mode: diagnosis and recommendations only; no remediation execution.
- Coverage: all 15 use cases documented.
- Memory: SQL-based episodic/curated memory first; pgvector deferred.
- First executable slice: PDB-blocked drain.

### Additional files
- `architecture/LANGGRAPH_DESIGN.md`: node state, edges, budgets and safety policy.
- `contracts/TOOL_CONTRACTS.md`: Splunk/Prometheus MCP adapter contracts and the separate object-collector boundary.
- `docs/OBSERVABILITY_REQUIREMENTS.md`: fleet-wide object/event allowlist, case matrix, field requirements, collector contract, security controls and acceptance tests.
- `db/migrations/001_initial.sql`: initial PostgreSQL schema.
- `db/README.md`: memory separation and retrieval approach.
- `tests/TEST_STRATEGY.md`, `tests/fixtures/pdb-blocked.json`: acceptance and safety tests.

**Important:** this is a design/documentation and schema pack, not a fully runnable production agent. The user's actual MCP tool schemas, cluster RBAC, release-matched runbook validation, deployment manifests, Python/LangGraph implementation and integration test execution remain prerequisites.


## Kubernetes object observability

All 15 scenarios now define case-specific Kubernetes object observability requirements in each scenario's `SPEC.md`, `design.md`, `plan.md` and `skill.md`. The shared inventory and ingestion design is in `docs/OBSERVABILITY_REQUIREMENTS.md`. The diagnostic agent does not call the Kubernetes API; it reads structured object history and Events from Splunk MCP and metrics from Prometheus MCP.
