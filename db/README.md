# PostgreSQL memory

`001_initial.sql` stores incident history, evidence provenance, hypotheses, recommendations, and curated knowledge. The runtime agent should not have DDL privileges and cannot write executable actions. Incident history is episodic memory; verified `sre_knowledge` is curated semantic memory; version-controlled `skill.md` files remain procedural memory. LangGraph checkpoints, if added, are transient workflow state and should use a separate retention policy.

Start with exact SQL retrieval by cluster, use case, OpenShift version, resource and verified status. Add pgvector only after building a labeled evaluation set and defining metadata filters; similarity alone must never establish a root cause. Do not persist raw secrets or full log payloads.
