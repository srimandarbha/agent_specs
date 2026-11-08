# Observability Requirements

The canonical requirement is now a **common baseline plus per-use-case object allowlist**, not a fixed Golden Six. The previous list actually named seven resource kinds and omitted objects explicitly required by several scenarios.

See [`OBSERVABILITY_MATRIX.md`](OBSERVABILITY_MATRIX.md) for the authoritative mapping of all 16 use cases to Kubernetes objects, fields, logs, metrics, freshness rules and collector safeguards.

## Evidence source topology

The default deployment uses two independently queried evidence adapters:

- Splunk MCP: logs, audit records, Events and Kubernetes object snapshots/changes when those datasets are actually ingested.
- Prometheus MCP: metric queries.

Centralizing metrics into Splunk is permitted as an alternative deployment profile, but must be declared in `manifest.json` and proven by adapter capability tests. Do not assume Prometheus metrics are available through Splunk just because the architecture diagram has one search box.

## Mandatory collector identity fields

Every object record must include `cluster_id`, API group/version, kind, namespace where applicable, name, UID, resourceVersion where available, event time, observation time and ingestion time. Deletions/tombstones or periodic authoritative snapshots are required to distinguish deletion from missing collection.

## Security

The collector has list/watch access only to approved object types. Secrets and credential-bearing fields are prohibited. Strip `metadata.managedFields`, environment variable values, raw MachineConfig file contents, webhook CA bundles and all credentials. The diagnostic agent itself has no Kubernetes API credentials or write permissions.

## Freshness

Use evidence-class-specific freshness thresholds. The starter targets are in `OBSERVABILITY_MATRIX.md`; calibrate them using measured end-to-end collection latency. A stale record can supply historical context but cannot satisfy a current-state safety precondition.
