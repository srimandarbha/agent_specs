# LangGraph Architecture and Routing Contract

## Chosen Pattern

Use a **deterministic workflow graph with bounded evidence and remediation matching**. The LLM may classify, summarize, rank hypotheses, and map variables, but cannot invent tool results, bypass gates, or execute arbitrary cluster mutations. 

The agent operates in a **read-only diagnostic mode**: it produces a verified root-cause diagnosis and maps the resolution to either an approved **Ansible Playbook spec** (for automated or human-approved AAP execution) or an exact **manual `oc` CLI fallback runbook**.

---

## Logical Nodes (10)

1. `ingest_event`: Accept alert or engineer request; assign `investigation_id` and idempotency key.
2. `normalize_context`: Validate cluster/node/MCP identity, event time, OpenShift version, source, and correlation identifiers.
3. `classify_lifecycle`: Classify lifecycle stage (`drain`, `config_apply`, `pivot_reboot`, `uncordon`, `mcp_rollout`, `cluster_upgrade`, or `unknown`).
4. `load_skill`: Load an allow-listed, versioned skill whose `use_case_id` and supported version range match.
5. `build_evidence_plan`: Formulate bounded query parameters for the unified Splunk multi-index search and KV Store lookup.
6. `query_unified_splunk_dossier`: Execute a **single round-trip multi-index SPL search** spanning `ocp_logs` (last 1h), `k8s_objects` / KV Store lookup (last 24h / live state for the Golden Six objects), and `ocp_metrics` (last 1h).
7. `assess_evidence`: Validate timestamps, cluster identity, freshness, completeness, and contradictions; deduplicate evidence.
8. `diagnose`: Generate ranked hypotheses strictly from recorded evidence and deterministic skill decision rules.
9. `match_remediation_plan`: Evaluate the diagnosed root cause against the **Ansible Playbook Catalog**:
   - **If an approved playbook matches:** Output the playbook ID, risk classification, and validated `extra_vars` ready for Ansible Automation Platform (AAP / AWX) execution.
   - **If no playbook matches or risk is high:** Generate an exact, copy-pasteable manual `oc` CLI fallback runbook with safety preconditions and verification steps.
10. `persist_and_report`: Persist incident metadata, evidence citations, and remediation specs to PostgreSQL, returning the final diagnostic report.

---

## Conditional Edges & Routing

```
[ingest_event]
       │
       ▼
[normalize_context] ──(invalid context)──► [persist_and_report] (inconclusive: invalid_context)
       │
       ▼
[classify_lifecycle] ──(unsupported)─────► [persist_and_report] (inconclusive: lifecycle_unknown)
       │
       ▼
[load_skill] ──────────(no skill match)──► [persist_and_report] (no_matching_skill)
       │
       ▼
[build_evidence_plan]
       │
       ▼
[query_unified_splunk_dossier]
       │
       ▼
[assess_evidence] ─────(missing data & budget remains)──► [build_evidence_plan] (max 2 rounds)
       │
       ▼ (evidence sufficient)
[diagnose]
       │
       ▼
[match_remediation_plan] ──► (Generates AAP extra_vars OR manual CLI fallback)
       │
       ▼
[persist_and_report] ─────► END
```

* `ingest_event -> normalize_context`: Invalid/missing cluster identity routes directly to `persist_and_report` with `inconclusive: invalid_context`.
* `normalize_context -> classify_lifecycle`: Unsupported lifecycle routes to `persist_and_report`.
* `classify_lifecycle -> load_skill`: No safe skill match routes to `persist_and_report`.
* `load_skill -> build_evidence_plan`: Loads required evidence schema and supported playbook rules.
* `build_evidence_plan -> query_unified_splunk_dossier`: Single multi-index search execution.
* `query_unified_splunk_dossier -> assess_evidence`: Parses returned dossier into structured state.
* `assess_evidence -> build_evidence_plan`: Triggers one bounded follow-up query if a material contradiction exists and budget remains; otherwise proceeds to `diagnose`.
* `diagnose -> match_remediation_plan`: Evaluates playbook preconditions against facts.
* `match_remediation_plan -> persist_and_report`: Outputs structured findings and remediation spec.
* `persist_and_report -> END`.

---

## Execution Bounds and Latency Targets

* **Investigation Deadline:** 45 seconds total execution time (dramatically reduced from 90s because multi-index query takes <10s).
* **Tool Call Budget:** Max **2 Splunk tool calls total** per investigation (1 primary multi-index query + at most 1 bounded follow-up).
* **Per-Query Timeout:** 15 seconds. Retry at most once for transient timeout/5xx errors with exponential backoff and jitter. Never retry authentication or query validation errors.
* **Evidence Time Windows:**
  * Logs (`index=ocp_logs`): `earliest=-1h latest=now`.
  * Object State (`index=k8s_objects` or KV Store): `earliest=-24h latest=now` (or instant KV Store lookup).
  * Metrics (`index=ocp_metrics`): `earliest=-1h latest=now`.
* **Hard Stop Safety:** The agent contains zero mutation tools. No `oc delete`, `oc patch`, or direct API writes. All remediation is handed off as a declarative spec.

---

## State Contract (`InvestigationState`)

The graph state encompasses:
* **Context:** `investigation_id`, `idempotency_key`, `trigger_type`, `cluster_id`, `cluster_name`, `openshift_version`, `node_name`, `mcp_name`, `lifecycle_stage`, `use_case_id`, `started_at`, `deadline_at`.
* **Evidence:** `dossier_raw`, `controller_log_errors[]`, `pdb_status`, `pod_status`, `node_annotations`, `volume_status`, `metrics_summary`, `tool_errors[]`.
* **Diagnosis:** `hypotheses[]`, `root_cause_hypothesis`, `confidence_band` (`high|medium|low`), `missing_evidence[]`.
* **Remediation Specification:**
  * `playbook_match_status` (`matched | no_match | approval_required`).
  * `playbook_spec`: `{ playbook_id, playbook_file, risk_level, aap_extra_vars: {} }`.
  * `manual_cli_fallback`: `{ step_descriptions[], commands[], safety_warnings[], verification_checks[] }`.
* **Outcome:** `persist_status`, `final_summary`.

---

## Operating and Safety Model

1. **Read-Only Ingestion:** Splunk MCP credentials require read-only search permissions restricted to `ocp_logs`, `k8s_objects`, and `ocp_metrics`.
2. **Deterministic Remediation Mapping:** The LLM cannot invent playbook names. It must select from the static `PLAYBOOK_CATALOG.json` schema.
3. **Auditability:** Every diagnosis outputs exact timestamped log lines, object resourceVersions, and metric values supporting the conclusion.
4. **PostgreSQL System of Record:** Metadata, hypotheses, and generated remediation specs are persisted to PostgreSQL using `db/migrations/001_initial.sql`.
