# Implementation Phase Task Cards & Acceptance Test Specifications

This document provides concrete, actionable engineering task cards for Phases 0 through 8 defined in [`DEVELOPMENT_BLUEPRINT.md`](../DEVELOPMENT_BLUEPRINT.md) §6. A smaller coding model must follow each task card in order and cannot declare a phase complete until all listed acceptance tests pass.

---

## Phase 0: Contract Hardening, Schemas & Reason Code Registry

### Task Card: `TC-PHASE-0`
- **Objective:** Establish strongly-typed Pydantic v2 schemas, define canonical reason codes, formalize MCP tool contracts, and specify the skill rule format.
- **Dependencies:** `contracts/`, `manifest.json`.
- **Target Deliverables:**
  - `schemas/`: `event.py`, `evidence.py`, `dossier.py`, `state.py`, `report.py`, `__init__.py`.
  - `contracts/REASON_CODES.md`: Full catalog of canonical stop reasons.
  - `contracts/SKILL_RULES.md`: Front matter schema and declarative AST rule spec.
  - `contracts/mcp_schemas/`: JSON schemas for Splunk and Prometheus MCP tools.
  - `contracts/samples/`: Real sample payloads for adapter responses.
- **Hard Invariants:**
  - All schemas must use Pydantic v2.
  - Zero synthetic/fictional MCP tool names.
  - No write tools allowed.
- **Acceptance Tests:**
  1. `pytest tests/test_schemas.py -q` passes 100%.
  2. `python3 tests/validate_repo_contracts.py` exits with code 0.
  3. `python3 -m compileall schemas contracts` returns 0 syntax errors.
- **Exit Gate:** All core schemas parse golden fixtures, reject malformed payloads, and enforce safety invariants (e.g., no playbook on inconclusive/not_supported).

---

## Phase 1: Observability Adapters & Read-Only Access Harness

### Task Card: `TC-PHASE-1`
- **Objective:** Implement `splunk_mcp` and `prometheus_mcp` clients adhering to [`contracts/MCP_INTEGRATION.md`](../contracts/MCP_INTEGRATION.md) and [`contracts/TOOL_CONTRACTS.md`](../contracts/TOOL_CONTRACTS.md).
- **Dependencies:** Phase 0 schemas (`schemas/evidence.py`, `contracts/mcp_schemas/`).
- **Implementation Work Items:**
  1. Create `adapters/base.py`: Define `EvidenceAdapter` protocol with `query()` and `capabilities()`.
  2. Create `adapters/splunk/`:
     - Implement `SplunkMCPAdapter` calling `query_unified_splunk_dossier`, `k8s_live_inventory_lookup`, and `query_broad_anomaly_dossier`.
     - Enforce hard time bounds (`earliest=-1h latest=now` for logs; `-24h` for objects) and max record limits (cap 200).
  3. Create `adapters/prometheus/`:
     - Implement `PrometheusMCPAdapter` calling `query_prometheus_instant` and `query_prometheus_range`.
     - Enforce cluster labeling and metric name allowlisting.
  4. Implement transient error handling: retry at most once for HTTP 503/timeout; fail-fast with `telemetry_backend_unavailable` without silent swallow.
- **Hard Invariants:**
  - Strictly read-only. Absolutely no direct Kubernetes API client, tokens, or write endpoints.
  - Parameterize all SPL and PromQL templates. Never interpolate unvalidated user or alert text.
- **Acceptance Tests:**
  1. `pytest tests/unit/test_adapters.py -q` (contract tests with mock MCP server).
  2. Test timeout handling: mock timeout returns normalized error, does not raise unhandled exception.
  3. Test query bounds: verify time range and record limits are injected into every query.
- **Exit Gate:** Mock adapter contract tests pass; adapter scopes and query budgets are verified by test assertions.

---

## Phase 2: Evidence Normalization & Deterministic Correlation Engine

### Task Card: `TC-PHASE-2`
- **Objective:** Ingest raw adapter query results, normalize them into canonical `EvidenceRecord` items, evaluate freshness and contradictions, and execute deterministic identity joins.
- **Dependencies:** Phase 0 schemas (`schemas/dossier.py`), Phase 1 adapters.
- **Implementation Work Items:**
  1. Create `evidence/normalizer.py`:
     - Map raw Splunk search rows and Prometheus metric vectors to `EvidenceRecord`.
     - Redact sensitive tokens and credentials before storing excerpts.
     - Compute content hashes (`sha256`).
  2. Create `evidence/freshness.py`:
     - Check evidence age against [`docs/OBSERVABILITY_MATRIX.md`](../docs/OBSERVABILITY_MATRIX.md) limits (e.g., 300s for active-incident PDB/Pod snapshots).
     - Mark records as `fresh` or `stale`.
  3. Create `correlation/engine.py`:
     - Implement deterministic joins:
       - PDB selector match against Pod labels in the same namespace.
       - OwnerReference resolution (Pod $\rightarrow$ ReplicaSet $\rightarrow$ Deployment).
       - Node name and MachineConfigPool correlation.
     - Detect contradictions: e.g. MCC eviction denial log present, but PDB `disruptionsAllowed > 0`.
- **Hard Invariants:**
  - Resource joins must be 100% deterministic code (zero LLM reasoning in joins).
  - Telemetry from a non-target `cluster_id` must immediately halt with `wrong_cluster_evidence`.
  - Empty results on backend errors must NOT be mapped to empty successes.
- **Acceptance Tests:**
  1. `pytest tests/unit/test_correlation.py -q`:
     - Verify PDB-to-Pod label matching matches golden dossier relationships.
     - Verify mismatched cluster ID triggers `wrong_cluster_evidence`.
     - Verify snapshot age > 300s triggers `pdb_state_stale`.
     - Verify contradiction detection between MCC log and PDB status.
- **Exit Gate:** Dossier correlation produces valid `RelationshipRecord` items and flags quality issues correctly on UC01 test fixtures.

---

## Phase 3: LangGraph State Machine & Persistence Harness

### Task Card: `TC-PHASE-3`
- **Objective:** Construct the 10-node dual-track LangGraph workflow, define routing edges, budget limits, and PostgreSQL persistence.
- **Dependencies:** Phase 0 `schemas/state.py`, Phase 1 adapters, Phase 2 correlation engine.
- **Implementation Work Items:**
  1. Create `graph/state.py`: Initialize `AgentState` with 45s deadline timer and adapter call counters.
  2. Create pipeline nodes:
     - `ingest_event`: Ingest envelope, validate schema, compute idempotency key.
     - `normalize_context`: Check cluster allowlist via `docs/CLUSTER_REGISTRY.md`.
     - `classify_lifecycle`: Deterministic regex/field classifier for lifecycle stage.
     - `load_skill`: Match signatures against allowlisted use cases.
     - `build_evidence_plan` & `assess_evidence`.
     - `persist_and_report`: Insert investigation trace into PostgreSQL (`db/migrations/001_initial.sql`).
  3. Implement conditional routing:
     - Unknown cluster $\rightarrow$ `persist_and_report` (`invalid_cluster_context`).
     - Unsupported lifecycle $\rightarrow$ `persist_and_report` (`lifecycle_stage_not_drain`).
     - Known use case (UC01-16) $\rightarrow$ Track A; Unknown $\rightarrow$ Track B.
- **Hard Invariants:**
  - Enforce total 45-second investigation deadline.
  - Maximum 2 Splunk tool calls per investigation.
  - Zero state transitions through unhandled exceptions.
- **Acceptance Tests:**
  1. `pytest tests/integration/test_graph_lifecycle.py -q`:
     - Test valid event transitions through full graph.
     - Test invalid cluster stops at `normalize_context`.
     - Test deadline expiration halts graph cleanly with status report.
     - Test duplicate event returns existing investigation record (idempotency).
- **Exit Gate:** Graph harness executes deterministically with mock adapters, terminates on all guard conditions, and commits audit records to DB.

---

## Phase 4: Use Case 01 Vertical Slice & E2E Evaluation Suite

### Task Card: `TC-PHASE-4`
- **Objective:** Deliver end-to-end diagnosis and remediation matching for Use Case 01 (`01-pdb-eviction-blocked`) across all 12+ fixture vectors.
- **Dependencies:** Phases 0 through 3, `use-cases/01-pdb-eviction-blocked/`.
- **Implementation Work Items:**
  1. Implement deterministic diagnosis node for UC01 conforming to `tests/evals/uc01_reference.py`.
  2. Implement `match_remediation_plan` node:
     - Evaluate preconditions against `remediations/PLAYBOOK_CATALOG.json`.
     - For Branch 3B (multi-replica at minAvailable): emit `playbook_pdb_scale_up` spec with exact `scale_to = current_replicas + 1`.
     - For Branches 3A, 3C, 3D: emit guarded manual CLI runbooks with safety warnings.
  3. Wire Prompt Injection defense: ensure untrusted logs are wrapped in `<untrusted_evidence_data>` and hard check rules from `tests/evals/uc01_checks.py` are enforced.
- **Hard Invariants:**
  - No `--force` or `--grace-period=0` in any manual CLI recommendation.
  - No playbook output when classification is `inconclusive` or `not_supported`.
  - Faithfulness score = 1.0 (exact pod/PDB/cluster names, zero hallucinated fields).
- **Acceptance Tests:**
  1. `pytest tests/evals/test_uc01_fixtures.py -q` passes all tests (oracle and graph agreement).
  2. Golden fixture `TC-01-POS-01` produces valid `expected_output.json`.
  3. Prompt-injection fixture `injection_in_log_dossier.json` produces identical output to golden without policy breach.
  4. Backend error fixture returns `inconclusive: telemetry_backend_unavailable`.
- **Exit Gate:** 100% pass on all UC01 fixtures in `tests/fixtures/01-pdb-eviction-blocked/`.

---

## Phase 5: Phased Rollout of Known Cases (UC02 - UC16)

### Task Card: `TC-PHASE-5`
- **Objective:** Incrementally activate Use Cases 02 through 16 in logical clusters.
- **Dependencies:** Phase 4 completion.
- **Batch Schedule:**
  - **Batch 5A (Eviction & Workload Blockers):** UC02 (Webhook admission), UC03 (Pod finalizers), UC04 (Storage unmount/detach), UC07 (Scheduling affinity/capacity).
  - **Batch 5B (OpenShift Virtualization):** UC05 (VM not migratable), UC06 (Stale virt-launcher).
  - **Batch 5C (Node & Infrastructure):** UC08 (Kubelet/CRI-O unreachable), UC09 (API/etcd latency), UC15 (Disk/host pressure), UC16 (CSI volume limits).
  - **Batch 5D (MCO & Node Rollout):** UC10 (MCP paused/coordination), UC11 (MCD config drift), UC12 (MCD render apply), UC13 (OS pivot reboot), UC14 (Uncordon/drain annotations).
- **Hard Invariants:**
  - Before any use case is marked active, all fixtures declared in its `eval.md` must be committed and verified by `tests/check_eval_fixtures.py`.
  - Every use case must have an executable reference oracle in `tests/evals/uc<id>_reference.py`.
  - Domain-expert review must approve the skill decision tree.
- **Acceptance Tests:**
  1. `python3 tests/check_eval_fixtures.py` shows 0 missing fixtures for enabled use cases.
  2. `pytest tests/evals/test_uc<id>_fixtures.py -q` passes for every enabled use case.
- **Exit Gate:** Each batch has 100% fixture coverage, reference oracle agreement, and passing evaluation tests.

---

## Phase 6: Track B (Exploratory Unknown Anomaly Track)

### Task Card: `TC-PHASE-6`
- **Objective:** Implement single-prompt exploratory anomaly diagnosis for incidents not matching UC01-16.
- **Dependencies:** Phases 0-3, `contracts/TOOL_CONTRACTS.md` §3.
- **Implementation Work Items:**
  1. Implement `build_broad_anomaly_plan` and `query_broad_anomaly_dossier`: single multi-index query capped at 50 records.
  2. Implement `synthesize_unknown_anomaly`: single bounded LLM call (**zero iterative tool loops**).
  3. Implement `format_sre_briefing`: strictly enforce `playbook_match: false`, `playbook_id: null`, confidence capped at `medium` or `low`, and output read-only diagnostic `oc` commands.
- **Hard Invariants:**
  - Exactly 1 LLM invocation; absolutely no tool calling loops.
  - Track B never outputs a playbook or executes remediation.
- **Acceptance Tests:**
  1. `pytest tests/evals/test_track_b.py -q`:
     - Test that Track B output schema strictly conforms to `InvestigationReport`.
     - Test invariant: `playbook_match == False` and `playbook_id == None`.
     - Test token cap $\le 2048$ tokens.
- **Exit Gate:** Exploratory dossiers generate structured SRE briefings without hallucinated playbook matches or tool call loops.

---

## Phase 7: Ansible Automation Platform (AAP) Remediation Handoff

### Task Card: `TC-PHASE-7`
- **Objective:** Implement the outbound integration contract for dispatching approved remediation specs to AAP/AWX.
- **Dependencies:** Phases 4-5, `remediations/REMEDIATION_EXECUTION.md`.
- **Implementation Work Items:**
  1. Implement `remediation/aap_client.py`:
     - Submit launch requests to AAP REST API using `aap_launch_spec`.
     - Verify explicit human approval token before dispatch.
  2. Implement asynchronous job tracking and post-remediation verification loop.
  3. Validate post-remediation conditions against declared skill verification goals.
- **Hard Invariants:**
  - Mutation is strictly external to the agent process; agent submits specifications only.
  - Human approval token is mandatory; no autonomous AAP dispatch without approval flag.
- **Acceptance Tests:**
  1. `pytest tests/integration/test_aap_handoff.py -q` (mock AAP server).
  2. Test rejection when approval token is missing.
  3. Test post-remediation verification polling and timeout behavior.
- **Exit Gate:** AAP launch payload validates against AAP job template schema and post-remediation verification confirms cluster recovery.

---

## Phase 8: Operational Readiness, Security Sign-Off & Rollout

### Task Card: `TC-PHASE-8`
- **Objective:** Complete security audit, load testing, HA verification, and production operational sign-off.
- **Dependencies:** All previous phases.
- **Implementation Work Items:**
  1. Security review against [`docs/SECURITY_REVIEW_CHECKLIST.md`](../docs/SECURITY_REVIEW_CHECKLIST.md).
  2. Load testing: 50 concurrent investigations under 45s SLA deadline.
  3. HA and database failover testing: verify Postgres connection pooling and Kafka offset commits.
- **Hard Invariants:**
  - Zero high/critical security vulnerabilities.
  - Pinned dependency versions in `requirements.lock`.
- **Acceptance Tests:**
  1. Full regression test suite: `pytest tests/ -q` passes 100%.
  2. Security audit checklist signed off.
  3. Load harness confirms 95th percentile investigation time $\le 35\text{s}$.
- **Exit Gate:** Production deployment sign-off by SRE and Security leads.
