# Kubernetes Object Observability Requirements for MCO Troubleshooting

This document is the entry point for the complete object requirements. The canonical, versioned mapping is [`docs/OBSERVABILITY_MATRIX.md`](docs/OBSERVABILITY_MATRIX.md).

## Corrected collection strategy

Do not use the term **Golden Six**. The original documentation enumerated seven object kinds, and the 16 skills additionally depend on Lease, CSINode, ClusterOperator, PVC/PV, Services/EndpointSlices, webhook configuration metadata, Deployments/ReplicaSets, DaemonSets and optionally minimal VMI/VMIM state.

Use a common baseline plus conditional, per-use-case resources. Only enable additional resources for scenarios deployed in the target fleet. This limits collector load while ensuring that every activated decision branch has the data needed to prove its preconditions.

## Mandatory additions to the original collector proposal

- `Lease` in `kube-node-lease` for UC08, UC09 and UC13.
- `CSINode` with driver allocatable counts for UC16.
- `ClusterOperator` for control-plane and operator health gates in UC09-UC13.
- `Service` and `EndpointSlice` plus non-sensitive webhook configuration metadata for UC02.
- `DaemonSet` for CSI node driver health in UC04. DaemonSet pods being ignored by drain does not make the driver irrelevant to diagnosis.
- `PersistentVolumeClaim` and selective `PersistentVolume` metadata for storage/topology correlation.
- `Deployment`/`ReplicaSet` for workload and controller readiness correlation.
- Optional minimal `VirtualMachineInstance`/`VirtualMachineInstanceMigration` status fields for UC05/UC06 when launcher Pod + Prometheus evidence cannot prove VM state. Do not ingest full VM specs or disk payloads.

## Source topology

The agent uses Splunk MCP for indexed logs/objects and Prometheus MCP for metrics by default. A centralized Splunk metrics deployment is acceptable only when explicitly configured and tested. Object collection is a separate, read-only telemetry pipeline; it does not grant the agent a Kubernetes API client.

## Safety and provenance

Never collect Secrets, private keys, kubeconfigs, tokens, `metadata.managedFields`, environment-variable values, raw MachineConfig file contents or webhook CA bundles. Each record must retain cluster ID, UID, resourceVersion where available, event/observed/ingested timestamps and a deletion/tombstone signal. Stale or missing data must be reported as an evidence gap, never as proof that a condition is absent.
