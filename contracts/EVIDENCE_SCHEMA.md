# Canonical Evidence and Dossier Schema

## Design rules

1. Every fact used in a diagnosis must point to one or more immutable evidence IDs.
2. Keep source timestamps distinct: `event_time`, `observed_at`, `ingested_at`, and query `retrieved_at`.
3. Identify resources by cluster + API group/version + kind + namespace (when namespaced) + name + UID. Use resourceVersion for snapshot ordering, not as a globally unique ID.
4. Keep raw excerpts bounded and redacted. Store summaries and hashes rather than full log payloads by default.
5. Represent unavailable, stale, malformed, contradictory and empty evidence as different states.

## Evidence record

```json
{
  "evidence_id": "ev-uuid",
  "source_adapter": "splunk_mcp",
  "source_dataset": "ocp_logs",
  "source_query_id": "query-uuid",
  "cluster_id": "ocp-prod-01",
  "resource": {
    "api_version": "v1",
    "kind": "Pod",
    "namespace": "payments",
    "name": "payments-api-xyz",
    "uid": "k8s-uid",
    "resource_version": "123456"
  },
  "evidence_type": "log|object_snapshot|object_change|event|metric|audit",
  "event_time": "2026-11-08T06:20:00Z",
  "observed_at": "2026-11-08T06:20:02Z",
  "ingested_at": "2026-11-08T06:20:04Z",
  "retrieved_at": "2026-11-08T06:20:05Z",
  "freshness": "fresh|stale|unknown",
  "quality": "valid|partial|malformed|contradictory",
  "fields": {},
  "excerpt": "bounded redacted excerpt",
  "content_hash": "sha256:...",
  "redaction_status": "redacted",
  "collector_version": "optional",
  "source_revision": "optional"
}
```

For metrics, add `metric_name`, labels, value, unit, sample timestamp, aggregation window, and query resolution. Do not put metric samples into `resource.name`.

## Dossier record

A dossier contains `investigation_id`, normalized context, query results per adapter, `records[]`, `relationships[]`, `missing_evidence[]`, `contradictions[]`, adapter errors, total elapsed time, per-adapter call counts and collection window. An empty successful query is `status=ok` with zero records; a failed query is `status=error`; stale-only results are `status=partial`. Never map an error to an empty success.

## Relationship record

```json
{
  "relationship_id": "rel-uuid",
  "type": "pod_covered_by_pdb",
  "from_evidence_id": "ev-pod",
  "to_evidence_id": "ev-pdb",
  "join_rule": "namespace_equal_and_selector_matches_labels",
  "result": "confirmed|candidate|ambiguous|rejected",
  "reason": "selector matched the pod labels in the same namespace"
}
```

## Diagnosis output

Every hypothesis includes a stable hypothesis ID, status (`supported`, `contradicted`, `unresolved`), confidence, rationale, supporting evidence IDs and contradicting evidence IDs. A diagnosis cannot be `supported/high` when a mandatory evidence gate is missing, stale, wrong-cluster or contradictory.
