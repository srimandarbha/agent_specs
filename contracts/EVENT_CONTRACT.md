# Event Contract

## Purpose

Normalize alert-driven and engineer-triggered investigations into one event envelope. Kafka is an optional transport; the same schema applies to an HTTP/manual entrypoint.

## Required envelope

```json
{
  "schema_version": "1.0",
  "event_id": "uuid-or-source-id",
  "event_type": "com.example.openshift.mco.drain.alert",
  "occurred_at": "2026-11-08T06:30:00Z",
  "received_at": "2026-11-08T06:30:02Z",
  "trigger_type": "alert",
  "source": "alertmanager",
  "cluster_id": "ocp-prod-01",
  "cluster_name": "ocp-prod-01",
  "openshift_version": "4.22.z",
  "node_name": "worker-01.example.invalid",
  "mcp_name": "worker",
  "alert": {
    "name": "MachineConfigControllerDrainError",
    "fingerprint": "stable-source-fingerprint",
    "severity": "warning",
    "labels": {},
    "annotations": {}
  },
  "request": {
    "text": null,
    "requested_by": null,
    "change_id": null
  },
  "trace_id": "optional-trace-id"
}
```

For `trigger_type=alert`, require source identity, event ID, cluster ID and alert name. For `trigger_type=manual`, require an authenticated principal and an explicit cluster ID; `alert` may be null and `request.text` may be supplied. Never infer a cluster from untrusted free text.

## Idempotency and ordering

- Preferred idempotency key: stable source fingerprint + cluster ID + alert name + normalized target resource + incident time bucket.
- Manual requests receive a unique request ID unless the caller explicitly supplies an approved idempotency key.
- Persist the source event ID and idempotency key under a unique constraint before graph execution.
- Duplicate deliveries return the existing investigation reference; they do not create parallel investigations.
- Preserve `occurred_at`, `received_at` and processing timestamps separately. Late events must not overwrite newer resource state.

## Validation and safety

Reject unknown schema versions, unknown clusters, malformed timestamps, oversized payloads, missing target context where required, and unexpected fields that could affect authorization. Treat alert labels, annotations, log excerpts and manual text as untrusted data, never as executable instructions. Redact credentials and sensitive values before persistence. Do not embed kubeconfigs, service-account tokens or secrets in events.

## Output event

An optional result event should include `investigation_id`, `event_id`, `cluster_id`, `terminal_status`, `use_case_id`, `classification`, `confidence`, `report_uri` or bounded report body, `created_at`, and schema version. Do not publish raw logs or secret-bearing evidence payloads.
