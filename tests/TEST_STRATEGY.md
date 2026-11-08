# Test strategy and acceptance gates

## Unit tests
- Lifecycle classifier handles drain, config apply, pivot/reboot, uncordon, MCP rollout, cluster upgrade and unknown.
- Skill loader rejects path traversal, unknown skill IDs, invalid schema and unsupported version range.
- Evidence assessor detects stale/future timestamps, wrong cluster, duplicate content hashes, missing event times and contradictions.
- Diagnosis cites evidence IDs; cannot cite nonexistent IDs or claim certainty when minimum evidence is absent.
- Retry policy retries only transient errors, at most twice; authorization errors are not retried.
- Redaction tests remove tokens, credentials, authorization headers and Secret values.

## Graph tests
- Missing cluster -> inconclusive; no tool invocation.
- Unknown skill -> no unbounded exploration.
- Unified multi-index Splunk query executes in a single call and finishes within the 15-second budget.
- Playbook Catalog matcher evaluates diagnosed root causes against `remediations/PLAYBOOK_CATALOG.json` and outputs valid `aap_extra_vars`.
- If no playbook matches or risk is high, matcher generates targeted manual `oc` CLI runbook with rollback instructions.
- Required evidence missing -> at most two rounds then inconclusive.
- All evidence sources unavailable -> report tool failures, not “no issue found”.
- Tool-call (max 2) and deadline (45s) budgets always terminate the graph.
- Tool registry containing a mutating operation causes startup/configuration failure.

## Integration tests (PDB first)
- Healthy PDB with allowed disruptions > 0 does not trigger a PDB-blocked diagnosis.
- PDB `disruptionsAllowed=0` plus matching pod and relevant eviction failure supports the hypothesis.
- `disruptionsAllowed=0` without matching target pod/eviction evidence is probable at most, not definitive.
- Selector mismatch, wrong namespace, stale telemetry, and another cluster's evidence must not support the diagnosis.
- PDB object history missing from Splunk yields an evidence gap, not a negative result; the agent does not query the Kubernetes API directly.
- Deployment replicas unavailable / unhealthy replacement pods are included as contextual evidence, not automatically called the sole root cause.
- Repeated event delivery with same idempotency key creates one investigation.
- PostgreSQL failure yields explicit persistence failure and no false success.

## Security and resilience
- Verify runtime RBAC cannot mutate Kubernetes resources or read Secrets.
- Verify queries have enforced cluster/time bounds and result limits.
- Verify SQL parameters are bound, not interpolated.
- Verify timeout, 429, 5xx, and permission-denied behavior.
- Load test concurrent investigations, pool limits, circuit breaking and database backpressure.
- Release gate: run against fixtures first, then read-only staging cluster, then limited production observation. No remediation enabled in this scope.


## Object observability integration tests across all 16 scenarios

- Confirm the agent queries only Splunk MCP and Prometheus MCP; no Kubernetes API tool is required or invoked.
- Confirm the separate collector emits allowlisted object snapshots, changes and Events with cluster ID, UID/resourceVersion where available, source event time, observation time and ingestion time.
- Exercise each case's `Kubernetes object observability requirements` section in its `SPEC.md`, `design.md`, `plan.md` and `skill.md`.
- Verify scenario-specific correlation gates for admission webhooks, finalizers, storage, OCV migration, scheduling, node Lease freshness, API/etcd latency, MCP/configuration rollout, reboot/pivot, uncordon coordination and disk pressure.
- Missing object history, stale data, wrong-cluster data, failed Splunk queries and collector gaps must never be treated as proof that the relevant condition is absent.
- Confirm the collector never emits Secret values, tokens, private keys or credentials and has no write permissions.
