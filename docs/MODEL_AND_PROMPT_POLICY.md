# Model and Prompt Policy

## Model responsibilities

Use deterministic code for context validation, lifecycle rules, evidence quality, correlation, arithmetic, catalog matching, safety and persistence. Use an LLM only for bounded interpretation of ambiguous alert language, explanation/synthesis of a normalized dossier, and user-readable report generation.

## Inputs

The model receives a structured context, the selected skill ID/version, relevant decision-tree excerpt, evidence records with stable IDs, explicit missing-data/contradiction markers, allowed classification enums and a JSON output schema. It does not receive credentials or unrestricted raw log streams.

## Output contract

The model may return hypotheses, classification proposal, confidence proposal, explanation and citations to supplied evidence IDs. Deterministic validators must reject unknown evidence IDs, fabricated resource fields, unsupported catalog IDs, unsafe instructions, malformed output and confidence inconsistent with evidence gates.

## Injection handling

Logs, Kubernetes annotations, Event messages, tickets, metric labels and manual text are untrusted evidence. Enclose and label them as data. Never allow their contents to override system policy or create new tools. Never execute generated commands. Do not let a model select an arbitrary skill path or query template.

## Model operations

Pin model/provider and prompt versions per release; log non-sensitive model metadata; measure token/cost/latency; implement timeout and fallback behavior. On malformed output or timeout, return a deterministic `inconclusive` report rather than retrying an open-ended conversation. Evaluate against golden, negative, contradictory, missing, stale and injection fixtures before changing a prompt/model.

## Track B

One bounded broad evidence query, one synthesis call, strict output shape, exploratory confidence, no playbook, no mutating action and explicit ruled-out cases only when supported by fresh evidence.
