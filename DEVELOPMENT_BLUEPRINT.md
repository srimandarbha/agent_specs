# Agent Development Blueprint

## 1. Product boundary

Build a multi-cluster, read-only diagnostic decision system for MCO drain stalls and related MCP rollout failures. It consumes alert/manual events, collects bounded evidence through approved observability adapters, applies deterministic correlation and versioned troubleshooting skills, uses an LLM only for bounded classification/synthesis where justified, and produces a recommendation. Mutation is outside the agent boundary. AAP execution is a separate, explicitly approved integration phase.

## 2. Runtime flow

1. Receive an event and validate its schema.
2. Resolve `cluster_id` through the cluster registry; reject unknown or disabled clusters before any evidence query.
3. Validate the event idempotency key and create an investigation record.
4. Normalize context: cluster, OpenShift version, node, MCP, incident time, lifecycle stage and trigger type.
5. Select a version-compatible skill from the allowlisted registry. The classifier may propose a skill, but deterministic trigger and version gates decide whether it can run.
6. Build an evidence plan from the selected skill's declared evidence requirements.
7. Query Splunk MCP for logs/object snapshots/events and Prometheus MCP for metrics. Use concurrency only where adapter limits and query budgets permit it.
8. Normalize raw results into the canonical evidence schema; validate cluster identity, resource identity, time, completeness, source and freshness.
9. Perform deterministic joins in the correlation engine. Preserve raw evidence references and derived relationship provenance.
10. Evaluate the skill decision tree. LLM output must be structured and may not create facts, identifiers, metric values, or evidence citations.
11. Resolve an approved catalog entry only when its preconditions and required evidence are satisfied. Otherwise generate a guarded manual runbook or an inconclusive report.
12. Persist evidence summaries, hypotheses, recommendations, skill/model/catalog versions and final report.
13. End the investigation. External execution and post-execution verification are separate events and do not mutate the original diagnosis record.

## 3. Recommended package boundaries

```text
agent/
  app/                 # startup, configuration, dependency wiring
  graph/               # LangGraph state, nodes, edges, limits
  domain/              # typed entities, enums, policy decisions
  adapters/
    splunk/            # Splunk MCP client and SPL templates
    prometheus/        # Prometheus MCP client and query templates
    kafka/             # ingress/egress adapters, if enabled
    postgres/          # persistence and checkpoint adapters
  evidence/            # normalization, redaction, freshness, provenance
  correlation/         # deterministic resource joins
  skills/              # skill registry/loader/validator
  diagnosis/           # deterministic rules and bounded LLM evaluators
  remediation/         # catalog matcher and runbook formatter
  policy/              # cluster scope, budgets, approvals, safety gates
  observability/       # metrics, tracing, structured logs
  schemas/             # JSON Schema/Pydantic contracts
  tests/               # unit, contract, graph, integration, eval, security
```

Keep the 16 Markdown skill packs as version-controlled procedural knowledge. Do not import executable Python from skill files. Skill metadata and decision rules should be validated and mapped to typed runtime rules.

## 4. LangGraph state requirements

At minimum include:

- `investigation_id`, `idempotency_key`, `event_id`, `trigger_type`
- `cluster_id`, `cluster_name`, `openshift_version`, `mco_version`, `node_name`, `mcp_name`
- `lifecycle_stage`, `use_case_id`, `skill_version`, `track`
- `started_at`, `deadline_at`, `query_count_by_adapter`, `retry_count_by_adapter`
- `evidence_refs`, `evidence_quality`, `missing_evidence`, `contradictions`
- `classification`, `confidence`, `hypotheses`, `supporting_evidence_ids`, `contradicting_evidence_ids`
- `recommendation_type`, `playbook_id`, `catalog_revision`, `recommendation_payload`
- `persist_status`, `terminal_reason`

Make state transitions explicit. The graph must terminate on unknown cluster, unauthorized scope, missing required context, incompatible skill, budget exhaustion, backend failure, persistence failure, or deadline expiry. Do not silently treat tool errors as empty evidence.

## 5. Separation of deterministic and LLM work

**Deterministic code owns:** schema validation, cluster authorization, trigger gates, skill/version selection, query construction, query bounds, tool budgets, retries, evidence normalization, identity joins, freshness, arithmetic, catalog matching, risk gates, persistence and final status.

**LLM may own:** mapping ambiguous natural-language alert text to candidate lifecycle/skill labels, interpreting a bounded set of normalized evidence, summarizing causal alternatives, and formatting an explanation against a strict output schema.

The LLM must not own: resource joins, deciding whether missing telemetry proves absence, generating arbitrary tool calls, inventing remediation IDs, or bypassing policy checks.

## 6. Build sequence and gates

| Phase | Deliverable | Exit gate |
|---|---|---|
| 0 | Evidence, event, cluster and skill contracts | Schemas reviewed; sample payloads validate |
| 1 | Adapters and read-only access | MCP contract tests pass; scopes/time bounds enforced |
| 2 | Evidence normalization/correlation | UC01 dossier joins PDB to Pod correctly; stale/mismatched inputs rejected |
| 3 | Graph harness and database | Idempotency, timeouts, retries, state transitions and persistence tests pass |
| 4 | UC01 vertical slice | Golden, negative, missing-data, contradiction, backend-error and injection tests pass |
| 5 | Remaining known cases in groups | Each case has complete data contract, fixture and tests before activation |
| 6 | Track B | One bounded query, one synthesis, strict exploratory schema, no playbook |
| 7 | AAP handoff | Separate approval, job tracking, audit and verification contracts tested in non-production |
| 8 | Production rollout | Security, load, HA, recovery, version pinning and operational acceptance signed off |

## 7. Default runtime budgets

The existing 45-second end-to-end and 15-second per-query values remain design targets, not proven SLAs. Configure budgets per adapter and deployment. The total deadline includes queue delay, adapter requests, retry/backoff, normalization, LLM inference and persistence. Retry only explicitly transient errors, at most once by default. Do not retry authorization, malformed query, schema, version-gate or cluster-scope failures.

A two-call global budget is not automatically compatible with two MCPs plus a follow-up query. Define call budgets per adapter and a total budget. Prefer one query per adapter and no follow-up unless required evidence is missing and remaining budget permits it.

## 8. Operational mode

Initial mode is read-only diagnosis and recommendations. Do not register write-capable Kubernetes tools in the process. AAP integration initially emits a recommendation payload only; launching a job requires a separate approval-bearing service identity and explicit job-template allowlist. Track B always returns `playbook_match=false` and `playbook_id=null`.
