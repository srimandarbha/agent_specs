# LangGraph architecture and routing contract

## Chosen pattern

Use a **deterministic workflow graph with bounded evidence/diagnosis loops**. The LLM may classify, summarize, and rank hypotheses, but cannot invent tool results, bypass gates, or execute mutations. There are no autonomous remediation nodes in this release. The supported outputs are diagnosis, evidence gaps, and recommendations.

## Logical nodes (12)

1. `ingest_event`: accept alert or engineer request; assign `investigation_id` and idempotency key.
2. `normalize_context`: validate cluster/node/MCP identity, event time, OpenShift version, source and correlation identifiers.
3. `classify_lifecycle`: classify `drain`, `config_apply`, `pivot_reboot`, `uncordon`, `mcp_rollout`, `cluster_upgrade`, or `unknown`.
4. `load_skill`: load an allow-listed, versioned skill whose `use_case_id` and supported version range match.
5. `build_evidence_plan`: create a bounded list of read-only calls from the skill's required evidence contract.
6. `query_splunk`: call the configured Splunk MCP log-search tool using validated, parameterized queries.
7. `query_prometheus`: call the configured Prometheus MCP query tool with approved PromQL and time bounds.
8. `query_splunk_object_history`: retrieve normalized Kubernetes object snapshots, changes and Events from Splunk MCP. The agent has no direct Kubernetes API tool; a separate read-only collector forwards allowlisted object evidence into Splunk.
9. `assess_evidence`: validate timestamps, cluster identity, freshness, completeness, and contradictions; deduplicate evidence.
10. `diagnose`: generate ranked hypotheses only from recorded evidence and skill rules.
11. `validate_diagnosis`: apply per-skill decision conditions, confidence/coverage gates, and stop rules.
12. `persist_and_report`: persist evidence and outcome, then return diagnosis, confidence, citations/references, unknowns and safe recommendations.

The graph can combine nodes 6–8 concurrently only when the selected skill declares the calls independent. If a tool is unavailable, record a tool error and continue only if the remaining evidence is sufficient; never silently substitute guessed evidence.

## Conditional edges

- `ingest_event -> normalize_context`; invalid/missing cluster identity routes to `persist_and_report` with `inconclusive: invalid_context`.
- `normalize_context -> classify_lifecycle`; unsupported/ambiguous lifecycle routes to a limited evidence plan or `inconclusive: lifecycle_unknown`.
- `classify_lifecycle -> load_skill`; no safe skill match routes to `persist_and_report` with `no_matching_skill`.
- `load_skill -> build_evidence_plan`; incompatible OpenShift version or unverified skill routes to `persist_and_report` with `version_gate_failed` unless the skill explicitly allows general read-only evidence gathering.
- `build_evidence_plan -> evidence nodes`; call only tools required by the skill and available under configured policy.
- evidence nodes -> `assess_evidence`.
- `assess_evidence -> build_evidence_plan` if required evidence is missing and `attempt_count < max_evidence_rounds` and `now < deadline`; otherwise -> `diagnose` if minimum evidence is met, else -> `persist_and_report` as inconclusive.
- `diagnose -> validate_diagnosis`.
- `validate_diagnosis -> build_evidence_plan` when a discriminating read-only query can resolve a material contradiction and budget remains; -> `persist_and_report` when evidence supports a diagnosis, or when the loop budget is exhausted (label uncertain/inconclusive as appropriate).
- `persist_and_report -> END`.

## Bounds and defaults (configurable, not OpenShift product defaults)

- Maximum evidence rounds: 3 total rounds; maximum 8 tool calls per investigation; max 2 calls per tool per round.
- Per MCP call timeout: 15 seconds; at most 2 retries for transient timeout/429/5xx with exponential backoff and jitter. Do not retry validation/auth/permission errors. Overall investigation deadline: 90 seconds for interactive requests; event-driven jobs may use a separately configured deadline.
- Evidence window default: event time ±15 minutes, capped at a skill-declared maximum; allow longer windows only when the lifecycle stage and query justify it.
- Evidence freshness: object state should be read at investigation time; telemetry must include event/ingestion timestamps and show its observed age. A stale result is not silently treated as current.
- Confidence is calibrated from explicit rule support/contradictions and evidence coverage; never present a raw LLM score as calibrated probability. If confidence is not calibrated against evaluation data, report `low/medium/high` with the rule basis.
- Hard stop: any mutation tool appears in a tool registry, a skill requests mutation, cluster identity is uncertain, or evidence crosses cluster boundaries. Return safe findings and flag the policy violation; do not execute.

## State contract

`InvestigationState` should include: `investigation_id`, `idempotency_key`, `trigger_type`, `event_payload_redacted`, `cluster_id`, `cluster_name`, `openshift_version`, `node_name`, `mcp_name`, `lifecycle_stage`, `use_case_id`, `skill_version`, `started_at`, `deadline_at`, `evidence_plan`, `evidence[]`, `tool_errors[]`, `hypotheses[]`, `contradictions[]`, `evidence_round`, `tool_call_count`, `diagnosis_status`, `root_cause_hypothesis`, `confidence_band`, `missing_evidence[]`, `recommendations[]`, `safety_flags[]`, `persist_status`.

Store evidence references and concise summaries, not unbounded raw logs. Redact credentials, tokens, authorization headers, secrets, and sensitive workload data before persistence. Raw evidence retention is governed by the source system policy.

## Node contract

Every node returns a partial state update and structured errors. Tool nodes must never return free-form strings alone. Minimum evidence record: `evidence_id`, `source` (`splunk|prometheus`), `tool_name`, `query_or_request_redacted`, `cluster_id`, `resource_ref`, `event_time`, `observed_at`, `ingested_at` if available, `result_summary`, `source_uri` or query/run reference, `freshness`, `content_hash`, `redaction_status`.

## Operating and safety model

- Read-only permissions only; separate service accounts per cluster or narrowly scoped identity, TLS verification, secret manager for credentials, no secrets in prompts or DB.
- The agent has no Kubernetes client. A separate object collector uses explicit GET/LIST and optionally WATCH only for allowlisted resources; it has no PATCH/UPDATE/DELETE/CREATE/EXEC/PORT-FORWARD. If the MCP server has mixed capabilities, enforce a local allow-list and test it.
- No AAP execution, ServiceNow change creation, pod deletion, PDB patch, finalizer clearing, node uncordon, MCP changes, VM changes, reboot, or storage detach in this diagnostic graph.
- Use an explicit allow-list of cluster IDs. Every tool request includes the validated cluster scope; reject cross-cluster queries.
- PostgreSQL is the system of record for cases/evidence metadata, not a replacement for live telemetry or authoritative Kubernetes state.
