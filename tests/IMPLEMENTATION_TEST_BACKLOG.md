# Executable Evaluation Backlog

## Required test assets before UC01 activation

- `tests/evals/conftest.py`: deterministic mock Splunk/Prometheus adapters, clock, DB fixture and graph factory.
- `test_event_contract.py`: schema version, required fields, unknown cluster and idempotency behavior.
- `test_tool_contracts.py`: parameterization, time bounds, result caps, auth/429/5xx/timeout semantics and adapter budgets.
- `test_evidence_schema.py`: timestamp provenance, redaction, wrong-cluster, stale, malformed and duplicate evidence.
- `test_correlation.py`: PDB selector joins, owner UID, PVC/PV/VolumeAttachment chain, Lease/Node, EndpointSlice/Service and CSI volume tally.
- `test_skill_loader.py`: path traversal, unknown ID, version gate, invalid metadata, content hash and disabled skill.
- `test_graph_boundaries.py`: graph deadline, bounded retries, max calls, cancellation and terminal routing.
- `test_recommendation_policy.py`: catalog-only IDs, extra_vars schema, unsupported preconditions, human approval and Track B no-playbook invariant.
- `test_persistence.py`: duplicate events, DB errors, append-only audit and redaction.
- `test_prompt_injection.py`: hostile log lines, annotations, Events and manual text never alter policy or tool registry.

## Fixture matrix

Every enabled use case needs, at minimum:

1. Canonical positive dossier.
2. Negative/non-fault dossier.
3. Missing mandatory evidence dossier.
4. Contradictory evidence dossier.
5. Stale or wrong-cluster dossier.
6. Backend unavailable/error case.
7. Relevant safety/prompt-injection case.

For any branch eligible for a playbook, add a positive case and at least one near-miss precondition case. Do not claim the 16-case suite is complete until every fixture reference in each `eval.md` resolves to a committed file and every expected output is validated against the schema.

## Repository validation utilities

- `python3 tests/check_eval_fixtures.py` verifies that every fixture path referenced by every `eval.md` exists. It currently reports missing references until those datasets are created; a failing result is expected and must not be misreported as a passing eval suite.
- `python3 tests/validate_repo_contracts.py` performs basic manifest/catalog/path consistency checks. It does not execute the graph or certify diagnosis quality.
