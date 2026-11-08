# Skill Registry and Loader Contract

## Skill package metadata

Each skill must declare structured YAML front matter conforming to [`contracts/SKILL_RULES.md`](../contracts/SKILL_RULES.md): `skill_id`, semantic `skill_version`, title, lifecycle stages, trigger signatures, supported OpenShift/MCO/KubeVirt/CSI versions, required evidence types and fields, freshness limits, decision-tree version, prohibited actions, remediation catalog references, evaluation fixture IDs, source references, and owner.

All exit codes, stop reasons, and uncertainty downgrade markers emitted by skills must be registered in [`contracts/REASON_CODES.md`](../contracts/REASON_CODES.md).

## Loading rules

- Skills are loaded only from the repository's allowlisted `use-cases/<id>/skill.md` paths resolved by the manifest; no user-supplied path or dynamic filesystem traversal.
- Validate skill ID against `manifest.json`, front matter/metadata schema, required sections, version compatibility and catalog references.
- Pin the skill content hash for each investigation and persist it with the result.
- A skill is disabled if required telemetry is unavailable, the supported OpenShift range does not match, a required source is not configured, or its evaluation gate is not passing.
- Markdown is procedural knowledge, not executable code. Do not evaluate embedded Python, shell or templates from `skill.md`.
- Parse diagnostic conditions into the constrained rule representation defined in [`contracts/SKILL_RULES.md`](../contracts/SKILL_RULES.md) or maintain their executable equivalent in reviewed code. Tests must prove the runtime behavior matches the document.
- **Prompt Injection Defense Injection:** Individual skills do not mention prompt injection. The loader and runtime harness inject security boundary directives and isolate untrusted evidence (logs, annotations, events) in strictly demarcated `<untrusted_evidence_data>` blocks.
- **Domain-Expert Pass Requirement:** Skills are subject to domain-expert review before activation to correct Kubernetes technical slips (e.g. UC01 overlapping PDB handling, UC03 finalizer location).

## Change management

Any change to trigger signatures, evidence requirements, decision rules, risk classification or remediation matching requires a fixture update and relevant evaluation run. Store skill versions immutably; do not silently replace the skill used by an in-flight investigation.
