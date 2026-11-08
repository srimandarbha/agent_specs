# LangGraph Architecture and Routing Contract

## Chosen Pattern: Dual-Track Bounded Workflow

The agent uses a **Deterministic State Machine with Bounded Cognitive Evaluators** operating in two distinct tracks:

1. **Track A (Known Scenario Track - Use Cases 01 to 16):** Strictly executes the deterministic decision trees defined in the loaded `skill.md`, matching approved Ansible Playbook specs or guarded manual CLI fallbacks.
2. **Track B (Exploratory Unknown Anomaly Track):** When an incident does not match any of the 16 known use cases, the Python engine deterministically collects a bounded error bundle from Splunk, and a dedicated cognitive node invokes the LLM **in exactly one prompt (zero iterative tool calls)** to synthesize the novel anomaly and provide a structured briefing and manual CLI inspection steps for the SRE.

The agent operates in a **strictly read-only mode** with zero cluster mutation tools.

---

## Logical Nodes (Dual-Track Architecture)

### Core Pipeline Nodes (Shared)
1. `ingest_event`: Accept alert or engineer request; assign `investigation_id` and idempotency key; start 45s timer.
2. `normalize_context`: Validate cluster/node identity, event time, OpenShift version, and resolve MCP name from node metadata.
3. `classify_lifecycle`: Classify lifecycle stage (`drain`, `config_apply`, `pivot_reboot`, `uncordon`, `mcp_rollout`, `cluster_upgrade`, or `unknown`).
4. `load_skill`: Match alert/log signatures against the 16 allow-listed use cases.

### Track A Nodes (Known Use Cases 01 - 16)
5. `build_evidence_plan`: Formulate bounded query parameters for the unified Splunk multi-index search and KV Store lookup.
6. `query_unified_splunk_dossier`: Execute a **single round-trip multi-index SPL search** spanning `ocp_logs`, `k8s_objects` / KV Store, and `ocp_metrics` (<10s).
7. `assess_evidence`: Validate timestamps, freshness, and contradictions; deduplicate evidence.
8. `diagnose`: Evaluate evidence strictly against the loaded `skill.md` decision tree to rank hypotheses.
9. `match_remediation_plan`: Evaluate diagnosed root cause against [`remediations/PLAYBOOK_CATALOG.json`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/remediations/PLAYBOOK_CATALOG.json):
   - Outputs Day-1 Ansible YAML Pseudo-code + verified variables.
   - Outputs copy-pasteable manual `oc` CLI fallback with safety checks.

### Track B Nodes (Exploratory Unknown Anomaly Track)
5b. `build_broad_anomaly_plan`: Formulate a bounded SPL query targeting top error/warning logs, warning events, and resource spikes on the target node.
6b. `query_broad_anomaly_dossier`: Execute a **single bounded Splunk search** (<5s) returning the top 50 anomalous events on that node.
8b. `synthesize_unknown_anomaly`: Single LLM cognitive invocation (**zero iterative tool loops**). Analyzes the error bundle, identifies the top 2-3 novel anomalies, and formulates a working hypothesis.
9b. `format_sre_briefing`: Enforces `playbook_match: false` / `null`, structures ruled-out standard cases, and outputs safe, read-only `oc` CLI commands for human SRE triage.

### Finalization Node (Shared)
10. `persist_and_report`: Persist incident metadata, evidence citations, and remediation specs to PostgreSQL ([`001_initial.sql`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/db/migrations/001_initial.sql)), returning the final report.

---

## Conditional Edges & Routing Flowchart

```
                            [ingest_event]
                                   │
                                   ▼
[normalize_context] ──(invalid cluster)─────────────► [persist_and_report] (inconclusive: invalid_context)
       │
       ▼ (valid context)
[classify_lifecycle] ──(unsupported stage)──────────► [persist_and_report] (inconclusive: lifecycle_unknown)
       │
       ▼ (stage == drain/upgrade)
  [load_skill]
       │
       ├──────────────────────────────────────────┐
       ▼ (Skill Matched: UC 01-16)                ▼ (No Skill Matched / Unknown Issue)
[build_evidence_plan]                      [build_broad_anomaly_plan]
       │                                          │
       ▼                                          ▼
[query_unified_splunk_dossier]             [query_broad_anomaly_dossier]
       │                                          │
       ▼                                          │
[assess_evidence]                                 │
       │                                          │
       ├─► (missing data & budget < 2) ──► loop   │
       │                                          │
       ▼ (evidence evaluated)                     │
[diagnose]                                        ▼
       │                                   [synthesize_unknown_anomaly]
       ▼                                   (Single LLM call - No tool loop)
[match_remediation_plan]                          │
       │                                          ▼
       │                                   [format_sre_briefing]
       │                                   (playbook_match: null enforced)
       │                                          │
       └────────────────────┬─────────────────────┘
                            │
                            ▼
                  [persist_and_report]
                            │
                            ▼
                          [END]
```

---

## Execution Bounds and Latency Targets

* **Investigation Deadline:** Strict 45 seconds total execution time across both tracks.
* **Tool Call Budget:** Max **2 Splunk tool calls total** per investigation (Track A: 1 primary + at most 1 follow-up; Track B: exactly 1 broad error query).
* **Per-Query Timeout:** 15 seconds. Retry at most once for transient timeout/5xx errors with exponential backoff and jitter. Never retry authentication or query validation errors.
* **Evidence Time Windows:**
  * Logs (`index=ocp_logs`): `earliest=-1h latest=now`.
  * Object State (`index=k8s_objects` or KV Store): `earliest=-24h latest=now` (or instant KV Store lookup).
  * Metrics (`index=ocp_metrics`): `earliest=-1h latest=now`.
* **Hard Stop Safety:** The agent contains zero mutation tools. No `oc delete`, `oc patch`, or direct API writes.

---

## State Contract (`InvestigationState`)

```python
class InvestigationState(BaseModel):
    # Context
    investigation_id: str
    idempotency_key: str
    trigger_type: str
    cluster_id: str
    cluster_name: str
    openshift_version: Optional[str]
    node_name: str
    mcp_name: Optional[str]
    lifecycle_stage: str
    use_case_id: Optional[str]
    track: str = Field(default="TRACK_A_KNOWN", description="TRACK_A_KNOWN or TRACK_B_EXPLORATORY")
    started_at: float
    deadline_at: float

    # Evidence
    dossier_raw: Optional[Dict[str, Any]]
    broad_anomalies_raw: Optional[Dict[str, Any]]
    query_count: int = 0
    tool_errors: List[str] = Field(default_factory=list)

    # Diagnosis
    classification: str  # supported | probable | inconclusive | not_supported | unclassified_anomaly
    confidence: str      # high | medium | low | exploratory
    summary: str
    ruled_out_scenarios: List[str] = Field(default_factory=list)
    anomalous_signals: List[Dict[str, Any]] = Field(default_factory=list)

    # Remediation (Two-Tier / Day-1 Pseudocode)
    remediation_type: str  # ANSIBLE_PLAYBOOK_PSEUDOCODE | MANUAL_CLI_RUNBOOK
    playbook_match: bool = False
    playbook_id: Optional[str] = None
    ansible_pseudocode: Optional[List[str]] = None
    manual_cli_fallback: Optional[Dict[str, Any]] = None

    # Outcome
    persist_status: Optional[str]
```

---

## Operating and Safety Model

1. **Deterministic Bounded Harness:** Track B exploratory triage **never** enters an open ReAct loop. The Python engine fetches the data; the LLM synthesizes it in a single prompt.
2. **Hardcoded Playbook Disablement for Unknowns:** Track B physically enforces `playbook_match = False` and `playbook_id = null`. Automated playbooks are strictly barred from executing on unclassified anomalies.
3. **Auditability:** Every diagnosis outputs exact timestamped log lines, object resourceVersions, and metric values supporting the conclusion.
4. **PostgreSQL System of Record:** Metadata, hypotheses, and generated remediation specs are persisted to PostgreSQL using [`db/migrations/001_initial.sql`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/db/migrations/001_initial.sql).
