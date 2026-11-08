# PostgreSQL memory

`001_initial.sql` stores incident history, evidence provenance, hypotheses, recommendations, and curated knowledge. The runtime agent should not have DDL privileges and cannot write executable actions. Incident history is episodic memory; verified `sre_knowledge` is curated semantic memory; version-controlled `skill.md` files remain procedural memory. LangGraph checkpoints, if added, are transient workflow state and should use a separate retention policy.

Start with exact SQL retrieval by cluster, use case, OpenShift version, resource and verified status. Add pgvector only after building a labeled evaluation set and defining metadata filters; similarity alone must never establish a root cause. Do not persist raw secrets or full log payloads.
## Schema evolution update

Apply `002_agent_contracts.sql` after reviewing `db/MIGRATION_NOTES.md`. It adds structured recommendation metadata, approval/external execution references, an append-only investigation event journal and richer evidence provenance. The migration does not relax the `execution_allowed = false` safety constraint.

Use separate database identities for the diagnosis agent, approval service, AAP integration and migration runner. Comments alone do not enforce column ownership: grant the agent no write privilege to approval or external execution fields. Existing historical `kubernetes_api` evidence values are retained, but the no-Kubernetes-API runtime profile must reject that adapter in code and tests.
