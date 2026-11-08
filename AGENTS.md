# Multi-Cluster MCO Diagnostic Agent: AI Coding Instructions & Engineering Standards

## 1. Mission & Boundary

Build a multi-cluster, read-only diagnostic decision system for OpenShift Machine Config Operator (MCO) drain stalls and related MachineConfigPool (MCP) rollout failures. 
The agent consumes alert or manual diagnostic events, gathers bounded evidence through approved MCP observability adapters (`splunk_mcp`, `prometheus_mcp`), applies deterministic correlation and versioned troubleshooting skills, uses an LLM only for bounded classification/synthesis where strictly justified, and produces an evidence-backed recommendation report.

**Hard Product Boundary:**
- Mutation is strictly outside the agent boundary. The agent process contains **zero write tools**, zero Kubernetes write privileges, and no direct Kubernetes API client.
- External remediation execution via Ansible Automation Platform (AAP/AWX) is an asynchronous, human-approved downstream handoff, never an autonomous agent action.

---

## 2. Technology Stack & Pinned Runtime Versions

The coding model must adhere strictly to the pinned runtime versions available in the environment:

| Component | Pinned Version | Purpose |
|---|---|---|
| **Python** | `3.12.3` | Execution runtime |
| **Pydantic** | `2.13.5` (`pydantic-core 2.46.5`) | Canonical schemas and validation |
| **LangGraph** | `1.2.12` (`checkpoint 4.2.0`, `prebuilt 1.1.0`) | Deterministic state machine orchestration |
| **LangChain Core** | `1.6.6` | Prompt and message serialization primitives |
| **Pytest** | `9.1.1` (`pluggy 1.6.0`) | Unit, contract, and evaluation test runner |
| **Psycopg** | `3.3.6` (`psycopg-pool 3.3.3`) | PostgreSQL persistence & audit storage |
| **Confluent-Kafka**| `2.15.1` | Event ingress/egress adapter (optional transport) |
| **HTTPX / AnyIO** | `0.28.1` / `4.15.1` | Async HTTP client for MCP and AAP integrations |
| **PyYAML** | `6.0.3` | Playbook catalog and skill front matter parsing |

---

## 3. How to Run Tests & Verification Commands

All code modifications must be proven by executing the relevant verification commands before claiming task completion:

```bash
# 1. Run full test suite (schemas, fixtures, contract tests)
pytest -q

# 2. Run UC01 deterministic oracle and fixture evaluation harness
pytest tests/evals -q

# 3. Run Pydantic contract and schema validation suite
pytest tests/test_schemas.py tests/test_mcp_schemas.py -q

# 4. Verify repository structural contracts and playbook catalog
python3 tests/validate_repo_contracts.py

# 5. Check evaluation fixture inventory completeness
python3 tests/check_eval_fixtures.py

# 6. Sanity check Python compilation across all modules
python3 -m compileall schemas contracts tests
```

---

## 4. Definition of Done (DoD)

A task or phase is complete **only** when all of the following conditions are met:
1. **Schema Conformity:** All event payloads, dossiers, evidence records, states, and reports validate against `schemas/` models with zero runtime validation errors.
2. **Canonical Reason Codes:** Every non-playbook termination emits a valid code registered in [`contracts/REASON_CODES.md`](contracts/REASON_CODES.md).
3. **The Tests Are the Gate:** All pytest tests and evaluation vectors pass cleanly. Fixtures must exist on disk; missing fixture references reported by `tests/check_eval_fixtures.py` disqualify the use case from activation.
4. **Safety Verification:** The test runner verifies that forbidden fragments (`--force`, `--grace-period=0`, `minAvailable: 0`, `delete pdb`, `patch pdb`) never appear in generated manual CLI commands or playbook parameters.
5. **Contract Validation:** `python3 tests/validate_repo_contracts.py` exits with code 0.
6. **Zero Write Tools:** No mutating Kubernetes tools, endpoints, or client libraries exist in the agent code.

---

## 5. Hard Rules for Coding Models

These rules are non-negotiable architectural invariants:

### Rule 1: Don't Invent MCP Tool Names
Platform access flows exclusively through approved adapters. Coding models must strictly bind to the tool definitions declared in [`contracts/mcp_schemas/`](contracts/mcp_schemas/):
- **Splunk MCP:** `query_unified_splunk_dossier`, `k8s_live_inventory_lookup`, `query_broad_anomaly_dossier`.
- **Prometheus MCP:** `query_prometheus_instant`, `query_prometheus_range`.
Never invent fictional tool names or parameter schemas.

### Rule 2: Register NO Write Tools
The diagnostic agent is strictly read-only. It has no Kubernetes API client, no cluster-admin token, and no mutation tools. It generates recommendations and structured remediation specs only.

### Rule 3: Don't Edit Skills
The 16 `skill.md` files in `use-cases/*/skill.md` represent versioned procedural knowledge and domain documentation. 
- Coding models must **NOT** rewrite, modify, or invent new skill Markdown files.
- The Skill Loader parses and normalizes them into the constrained rule format defined in [`contracts/SKILL_RULES.md`](contracts/SKILL_RULES.md).
- Factual errors in skills (such as UC01 overlapping PDB handling or UC03 finalizer locations) must be documented in `contracts/SKILL_RULES.md` and corrected exclusively through human domain-expert review passes.

### Rule 4: The Tests Are the Gate
Never claim completion of a use case or phase without committed fixtures and passing tests. Mocking assertions or faking test passes is strictly prohibited. Every phase must satisfy its task card exit gate in [`docs/PHASE_TASK_CARDS.md`](docs/PHASE_TASK_CARDS.md).

### Rule 5: Prompt Injection Is Injected by the Loader
Skills do not encode prompt injection defenses. The Skill Loader and Graph Harness isolate all untrusted evidence (logs, annotations, event messages, tickets) within `<untrusted_evidence_data>` blocks, and inject system prompt constraints prohibiting instruction execution from data.

### Rule 6: Deterministic Code Owns All State Logic
Follow [`DEVELOPMENT_BLUEPRINT.md`](DEVELOPMENT_BLUEPRINT.md) §5. Deterministic code owns schema validation, cluster authorization, trigger gates, skill selection, query bounds, evidence normalization, resource joins, PDB arithmetic, catalog matching, risk gates, and persistence. The LLM is used only for bounded interpretation and user report formatting.

### Rule 7: Balanced Observability Architecture
Prometheus is a first-class logical adapter. Splunk and Prometheus are equal peers in the federated telemetry architecture:
- Logs, object snapshots, and Events $\rightarrow$ `splunk_mcp`.
- Metrics, gauges, counters, and rates $\rightarrow$ `prometheus_mcp`.

---

## 6. Repository Layout & Authoritative References

- `schemas/`: Strongly-typed Pydantic v2 data models (`event.py`, `evidence.py`, `dossier.py`, `state.py`, `report.py`).
- `contracts/`: Authoritative contracts:
  - `EVENT_CONTRACT.md`: Ingress envelope and idempotency key specification.
  - `EVIDENCE_SCHEMA.md`: Canonical evidence and dossier schema.
  - `CORRELATION_ENGINE.md`: Deterministic entity relationship join rules.
  - `TOOL_CONTRACTS.md`: Query parameter limits and remediation specs.
  - `MCP_INTEGRATION.md`: Adapter protocols and query budgets.
  - `REASON_CODES.md`: Authoritative registry of all stop reason codes.
  - `SKILL_RULES.md`: Machine-readable front matter and declarative rule AST spec.
  - `mcp_schemas/`: JSON schemas for Splunk and Prometheus MCP tools.
  - `samples/`: Real sample payloads for adapter responses.
- `docs/`: System documentation:
  - `PHASE_TASK_CARDS.md`: Per-phase task breakdown and acceptance tests (Phases 0-8).
  - `SKILL_LOADER.md`: Skill loader and runtime isolation contract.
  - `OBSERVABILITY_MATRIX.md`: Freshness limits and required telemetry matrix.
  - `MODEL_AND_PROMPT_POLICY.md`: LLM governance, budgets, and prompt injection policy.
  - `SECURITY_MODEL.md` & `SECURITY_REVIEW_CHECKLIST.md`: Threat model and security controls.
- `use-cases/`: 16 troubleshooting packs (`01-pdb-eviction-blocked` to `16-csi-max-volume-limit-exceeded`).
- `tests/`:
  - `evals/`: Reference oracles, hard-pass checks, and evaluation suites.
  - `fixtures/`: Committed JSON test vectors and expected outputs.
  - `test_schemas.py`: Schema validation unit suite.
  - `test_mcp_schemas.py`: MCP tool and sample validation suite.
- `remediations/`: `PLAYBOOK_CATALOG.json` and remediation execution policies.
- `db/migrations/`: PostgreSQL relational audit and state migrations.
