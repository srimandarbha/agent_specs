# Agent Observability and SLO Contract

## Metrics

Recommended low-cardinality metrics:

- `agent_investigations_total{trigger_type,use_case_id,terminal_status}`
- `agent_investigation_duration_seconds{use_case_id,terminal_status}`
- `agent_adapter_requests_total{adapter,operation,status}`
- `agent_adapter_request_duration_seconds{adapter,operation}`
- `agent_evidence_records_total{adapter,evidence_type}`
- `agent_evidence_quality_total{quality,freshness}`
- `agent_missing_evidence_total{use_case_id,evidence_type}`
- `agent_diagnosis_total{use_case_id,classification,confidence}`
- `agent_budget_exhaustions_total{budget_type}`
- `agent_llm_calls_total{purpose,status}` and `agent_llm_duration_seconds{purpose}`
- `agent_persistence_operations_total{operation,status}`
- `agent_recommendations_total{recommendation_type,risk_level}`

Do not use cluster name, node, namespace, pod, user, alert fingerprint or ticket number as metric labels. Put those in access-controlled structured logs/traces when operationally necessary.

## Tracing

Propagate trace/correlation IDs from event ingress through graph nodes, MCP requests, model requests and PostgreSQL operations. Record node name, duration, outcome and sanitized request ID. Do not attach raw logs, credentials, prompts containing sensitive values or unbounded payloads to spans.

## SLO definition

The repository's 45-second investigation deadline is a target, not an established SLO. Before declaring an SLO, measure event queue delay, adapter latency, LLM inference, persistence and concurrency under realistic fleet load. Publish percentiles and error budget by terminal status, not only a single average.
