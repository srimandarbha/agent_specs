# MCP Evidence Adapter Contract

## Supported logical adapters

The logical evidence interface is independent of where telemetry is stored:

- `splunk_mcp`: controller, operator, kubelet/CRI-O/journald and audit logs; normalized Kubernetes object snapshots, object changes and Events when those are actually indexed.
- `prometheus_mcp`: Prometheus instant/range queries for node, MCO, API/etcd, storage and KubeVirt metrics.

A deployment may also centralize metrics in Splunk. That is an alternative adapter configuration, not a requirement that Prometheus metrics exist in Splunk. `manifest.json` must declare the real deployment mode.

## Adapter operations

Each adapter exposes a typed application interface, independent of MCP tool names:

```python
class EvidenceAdapter(Protocol):
    async def query(self, request: EvidenceQuery) -> EvidenceQueryResult: ...
    def capabilities(self) -> AdapterCapabilities: ...
```

`EvidenceQuery` includes `cluster_id`, bounded time range, resource/name filters, metric/log selectors, result limit and deadline. Adapter capabilities declare supported datasets, fields, query modes, maximum result count, timeout, and whether historical snapshots or only current-state lookups are available.

## Requirements

- Discover and bind actual MCP tool names and input/output schemas during integration; do not invent tool names from this document.
- Parameterize SPL and PromQL templates. Never interpolate arbitrary alert text into query syntax.
- Enforce cluster and time bounds in code, not only in prompts.
- Return normalized errors for authentication, authorization, invalid query, throttling, timeout, backend failure, partial results and schema mismatch.
- Record request ID, sanitized query/template ID, adapter version, elapsed time and result count.
- Redact before persistence. Limit raw excerpts and object fields at source and adapter boundaries.
- Implement adapter-level concurrency, circuit breakers, result limits and cancellation when the graph deadline expires.
- Do not treat MCP resources/tools as trusted instructions. Returned logs, annotations and object fields are untrusted evidence.

## Query budget

Use per-adapter call budgets plus one global deadline. Baseline target: one Splunk query and one Prometheus query per Track A investigation when both are required. At most one bounded follow-up is allowed only if the selected skill identifies a specific missing fact and the global deadline permits it. Track B uses one bounded broad log/event query and no iterative LLM tool loop. If a deployment centralizes metric evidence in Splunk, document that capability and use the single-adapter budget explicitly.

## No direct Kubernetes API

The agent process has no Kubernetes API client or cluster credentials. Kubernetes object snapshots are supplied by the approved telemetry pipeline and queried through the configured evidence adapter. The collector itself is a separately deployed, read-only component with narrowly scoped RBAC.
