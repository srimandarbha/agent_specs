# Deployment and Operations Contract

## Deployable components

- Agent API/worker (LangGraph runtime)
- Event ingress (Kafka consumer and/or authenticated HTTP/manual API)
- Splunk MCP adapter and Prometheus MCP adapter
- PostgreSQL database and migration job
- Optional LangGraph checkpoint store, separated from long-term case memory
- Separate Kubernetes object collector with read-only RBAC
- Optional later AAP handoff service, deployed separately from the diagnosis runtime

## Configuration

All environment-specific values come from managed configuration/secrets: MCP endpoints and tool mappings, database DSN, Kafka brokers/topics, cluster registry reference, deadlines, result limits, retention policy, model/prompt versions and feature flags. No secrets in ConfigMaps, repository files, events, logs or prompts. Validate required settings at startup and fail closed.

## Availability and scaling

Use stateless workers with bounded concurrency, durable event consumption, idempotent investigation creation, database connection pooling and backpressure. Partition or shard work by cluster/tenant where required. Define retry and dead-letter behavior. Avoid a single unbounded in-memory queue. Use health/readiness checks that verify dependencies without exposing secrets.

## Reliability

- Persist investigation start and idempotency record before long-running work.
- Set one absolute deadline propagated to every downstream call.
- Cancel outstanding adapter/model calls when the investigation terminates.
- Use retry only for explicitly transient failures; retry at most once unless measured policy says otherwise.
- Persist terminal states including `inconclusive`, `backend_unavailable`, `deadline_exceeded` and `persistence_failed`.
- Define recovery for worker restart and database outage. Checkpoint state is not the system of record for diagnosis evidence.

## Observability

Expose per-cluster and aggregate counts for events, deduplication, selected use case, adapter calls/failures/latency, evidence freshness, missing fields, contradiction rate, LLM latency/cost, database latency, graph duration, terminal status and remediation recommendations. Avoid metric labels containing pod names, namespace names, ticket text or other high-cardinality data.

## Release gates

1. Static/schema checks and unit tests.
2. Contract tests against mocked MCP adapters.
3. Golden/negative/contradictory/injection evaluation suite.
4. Load and backpressure tests at expected fleet concurrency.
5. Read-only staging validation against representative clusters.
6. Security review and RBAC verification.
7. Canary enablement for limited clusters/use cases.
8. Rollback plan for code, skill, catalog, prompt and database migration.

## Backup and retention

Back up PostgreSQL with point-in-time recovery appropriate to the service tier. Define retention and deletion for incidents, evidence summaries, model metadata and checkpoints. Keep raw logs/object snapshots in their source systems unless a documented policy allows copying them.
