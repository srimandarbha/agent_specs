# Intent: Federated Observability Architecture for MCO/MCP Troubleshooting

**Status:** Approved architectural direction, subject to implementation gates  
**Scope:** Multi-cluster OpenShift MCO drain stalls and MCP rollout failures  
**Operating mode:** Read-only diagnosis and recommendations  
**Authoritative configuration:** `manifest.json`, this document, `DEVELOPMENT_BLUEPRINT.md`, and the contracts under `contracts/`

## 1. Purpose and constraints

Build a bounded diagnostic decision system for the 16 versioned troubleshooting skills in `use-cases/`. The agent correlates logs, Kubernetes object snapshots, and metrics without direct Kubernetes API access. It must not operate Kubernetes or execute remediation.

The initial evidence sources are two distinct adapters:

- **Splunk MCP:** container/operator/journald logs, Events and normalized Kubernetes object snapshots/KV Store records.
- **Prometheus MCP:** instant and range metric queries.

A deployment may optionally ingest Prometheus metrics into Splunk. That is an alternate data-availability profile, not the default architecture and not a reason to merge the two logical adapters. The evidence schema must preserve the actual originating source and timestamp.

## 2. Architecture

```text
Alert / Manual Request
        |
        v
Event validation + cluster registry authorization
        |
        v
Versioned skill selection + bounded evidence plan
        |
        +----------------------+----------------------+
        |                                             |
        v                                             v
   Splunk MCP                                   Prometheus MCP
 logs + K8s snapshots + Events                  instant + range metrics
        |                                             |
        +----------------------+----------------------+
                               |
                               v
                 Evidence normalization / redaction
                               |
                               v
                 Deterministic correlation + provenance
                               |
                               v
                  Skill decision tree / bounded LLM
                               |
                               v
                  Recommendation + persisted report
```

The LLM may classify ambiguous alert text, compare bounded hypotheses and summarize evidence. Deterministic code owns authorization, skill selection, query construction, budgets, normalization, freshness, joins, arithmetic, risk gates, remediation matching and persistence.

## 3. Evidence and query boundaries

Every query must be cluster-scoped, time-bounded, allowlisted and capped. Query budgets are **per adapter plus a total investigation deadline**, not a fictional single round-trip across independent systems.

- Splunk queries return bounded logs, Events and object records. Prefer KV Store lookups for current object snapshots where supported.
- Prometheus queries use reviewed metric templates and allowlisted label dimensions. Do not accept arbitrary model-generated PromQL.
- Run independent adapter calls concurrently only where adapter capacity and query budgets permit.
- A backend error is not an empty result. Preserve `error`, `partial`, `empty` and `ok` as distinct outcomes.
- Every evidence item carries cluster identity, source, resource identity where applicable, event/observation/ingestion timestamps, query reference and freshness assessment.
- Correlation must prove joins using stable identifiers, owner references, selectors and namespace. Do not infer relationships from coincidental names or aggregate unrelated resources.

See [`contracts/TOOL_CONTRACTS.md`](contracts/TOOL_CONTRACTS.md), [`contracts/EVIDENCE_SCHEMA.md`](contracts/EVIDENCE_SCHEMA.md), [`contracts/CORRELATION_ENGINE.md`](contracts/CORRELATION_ENGINE.md), and [`docs/OBSERVABILITY_MATRIX.md`](docs/OBSERVABILITY_MATRIX.md).

## 4. Kubernetes object telemetry

The collection model is a **common baseline plus per-use-case additions**, not a fixed “Golden Six” list. The matrix is the source of truth for object kinds and minimum fields. Collect only fields needed by enabled skills. Never collect Secrets, token values, private keys, kubeconfigs, environment-variable values, `managedFields`, raw MachineConfig file contents or unredacted CSI credentials.

The Splunk inventory adapter must support:
- exact object lookup by cluster, kind, namespace and name;
- bounded list lookup by cluster, kind and optional namespace;
- selector filtering only when the collector has indexed the required labels;
- explicit pagination/record caps and snapshot timestamps.

If the underlying Splunk dataset does not contain a requested kind or field, return `unsupported` or `not_collected`, not an empty list that could be misread as proof of absence.

## 5. Runtime and latency budgets

The 45-second end-to-end and 15-second per-query values in `DEVELOPMENT_BLUEPRINT.md` are initial **design targets**, not measured service-level objectives. Configure them per deployment and measure queueing, adapter latency, normalization, LLM inference and persistence independently. Retries are limited to explicitly transient failures and must fit within the original deadline.

## 6. Safety boundary

The agent is read-only. It does not receive Kubernetes write credentials and does not register write-capable tools. Remediation output is a recommendation only. AAP job launch, approval, execution and post-execution verification are separate workflows with separate identities, audit records and policy gates. Track B exploratory diagnosis never produces an executable playbook match.

## 7. Implementation status

This repository is a specification and contract pack, not yet a production runtime. Python schemas and UC01 oracle tests are scaffolding. The LangGraph runtime, concrete MCP adapters, skill loader, persistence implementation, complete fixture coverage and executable Ansible playbooks must pass their respective gates before production use.
