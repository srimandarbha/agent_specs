# Read-only tool contracts

The agent tool names and schemas must be mapped to the actual Splunk MCP and Prometheus MCP. The agent has no Kubernetes API/MCP tool. A separate read-only collector forwards allowlisted Kubernetes object snapshots, changes and Events into Splunk; its deployment/RBAC contract is documented in `../docs/OBSERVABILITY_REQUIREMENTS.md`.

## Common envelope

Inputs: `cluster_id` (allow-listed), `time_start`, `time_end`, `request_id`, bounded query parameters. Outputs: `tool_name`, `request_id`, `status` (`ok|timeout|permission_denied|invalid_query|unavailable|error`), `observed_at`, `source_reference`, `records[]`, `truncated`, `error_code`. All timestamps UTC ISO-8601; enforce maximum time span and result count.

## Splunk log search

- Input: approved SPL template ID, named parameters (cluster/node/pod/container/time range), max results.
- Output each result with event timestamp, index/sourcetype, cluster/resource identifiers, redacted message excerpt, stable event/reference ID when available.
- Do not accept arbitrary user-provided SPL without validation. Escape literals or use parameterized templates; prohibit searches that omit cluster/time constraints unless explicitly approved.

## Prometheus query

- Input: approved query/template ID, validated label values, start/end/step or instant timestamp, max series/sample count.
- Output: metric name, labels, timestamp, value, query reference, query evaluation status.
- Use approved PromQL templates. Bound range, resolution and series count. Missing series is `unknown`, not zero.

## Kubernetes object evidence via Splunk

- Agent input: approved Splunk query template ID and bounded cluster/resource/time parameters.
- Expected records: normalized object snapshots/change records/Events emitted by the separate collector, with cluster ID, kind, namespace/name/UID, resourceVersion when available, source event time, observed time and ingestion time.
- Query only approved fields and resource kinds; validate selector semantics in the diagnosis logic rather than relying on string matches.
- The collector, not the agent, has narrowly scoped Kubernetes `GET`/`LIST` and optionally `WATCH` permissions. No Secret reads or write verbs. See `../docs/OBSERVABILITY_REQUIREMENTS.md`.
- A missing historical snapshot is an evidence gap, not proof that a condition was absent.

## Error and retry policy

Retry only timeout, rate-limit and transient server errors, max two retries with exponential backoff + jitter. Do not retry authorization/validation failures. Record every failed attempt in `tool_errors`; never reinterpret failure as a negative finding. Circuit-break repeated failures for a tool during one investigation.
