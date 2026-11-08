# Deterministic Evidence Correlation Engine

## Responsibility

The correlation engine is ordinary typed application code, not an LLM prompt. It converts separately retrieved log, object and metric records into explicitly proven relationships. It must preserve the source evidence IDs for each derived fact.

## Required joins by scenario

| Relationship | Deterministic join |
|---|---|
| MCC drain log to Pod | Extract namespace/name from the log; match Pod identity in the same cluster and a time-compatible snapshot |
| Pod to PDB | Same cluster and namespace; evaluate `PodDisruptionBudget.spec.selector` against Pod labels; support `matchLabels` and `matchExpressions`; detect zero, one or multiple matching budgets |
| Pod to owner | Follow `metadata.ownerReferences` by UID, not only name; collect owner kind/name/UID |
| Pod to PVC | Resolve `spec.volumes[*].persistentVolumeClaim.claimName` in the same namespace |
| PVC to PV | Resolve `spec.volumeName`; retain PVC/PV phase and storage class metadata |
| PV to VolumeAttachment | Match persistent volume name and driver; use attachment node and status; do not infer detach completion from object absence without fresh tombstone/change history |
| Node to Lease | Match `kube-node-lease` Lease name to Node name; validate holder identity and compare `spec.renewTime` with event time |
| Pod to scheduler Event | Match involved object UID where available; otherwise same namespace/name plus bounded time correlation |
| Node to MCP | Use node labels and MCP selector; detect overlap or no matching pool |
| Node to MachineConfig | Match node current/desired config annotations to MachineConfig names and MCP rendered config references |
| Pod to VMI | Match `kubevirt.io` and `vm.kubevirt.io/name` labels plus namespace; require a current VMI/launcher snapshot or an explicitly validated metric alternative |
| CSI attachment capacity | Group fresh `VolumeAttachment` records by node and CSI driver; compare with matching driver's `CSINode.allocatable.count`; distinguish attachment object count from actual driver-specific limit semantics |
| Webhook to endpoint | Match webhook client configuration's service reference to Service namespace/name, then Service selector/ports to ready EndpointSlices; do not collect `caBundle` or Secret data |

## Result semantics

- `confirmed`: all keys and required fields are present, fresh and unambiguous.
- `candidate`: a plausible match exists but one or more required facts are incomplete.
- `ambiguous`: multiple resources match or historical identity is insufficient.
- `rejected`: explicit selector/identity mismatch.
- `unavailable`: source query failed or required collector data is absent.

## Important safeguards

- Never join solely on resource name across clusters or namespaces.
- Prefer UID and ownerReference UID. A name-only fallback must be marked lower confidence.
- Use resourceVersion and observation timestamps to order snapshots; do not compare resourceVersions across different objects.
- PDB status and Pod labels must come from compatible observations. A stale PDB cannot conclusively explain a current eviction error.
- Missing event history is not evidence that an event did not occur.
- Do not sum metrics with different label dimensions or aggregation windows without a documented transformation.
- For CSI limits, distinguish CSI driver per-node attach limits, cloud provider limits, per-volume constraints and storage topology. A count alone does not prove a scheduler limit unless it matches the exact scheduler/driver semantics.
