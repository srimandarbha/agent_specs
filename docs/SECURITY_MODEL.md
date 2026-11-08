# Security Model

## Trust boundaries

1. **Event ingress:** Alertmanager/Kafka/manual API is untrusted input. Authenticate producers and principals; validate schema and cluster scope.
2. **Evidence adapters:** Splunk and Prometheus are read-only data sources. MCP responses are untrusted data, not instructions.
3. **Object collector:** A separately deployed read-only telemetry component. It is not the diagnostic agent and must not have write privileges.
4. **LLM boundary:** The model receives bounded, redacted evidence. It cannot select arbitrary tools or execute commands.
5. **Persistence:** PostgreSQL stores redacted investigation summaries and provenance. Migration role owns DDL; runtime role cannot change schema.
6. **Remediation boundary:** The diagnostic agent emits recommendation payloads only. A separate approval/AAP service owns launch credentials and job execution.

## Identity and authorization

- Authenticate every event producer and manual requester.
- Resolve cluster IDs from an allowlisted registry. Do not accept an arbitrary cluster URL, kubeconfig or bearer token from event payloads.
- Enforce tenant/cluster scope in adapter queries and database access.
- Use distinct service identities for ingress, evidence queries, persistence, collector and AAP integration.
- Use Vault or the enterprise secrets manager for credentials. Never place tokens or passwords in Git, prompts, logs, event bodies or SQL text.

## Minimum privileges

- Agent: Splunk search-only on approved indexes and Prometheus query-only on approved data; PostgreSQL select/insert/update only on required agent tables; no Kubernetes API credentials; no shell/SSH write tools; no AAP launch credential in diagnosis mode.
- Collector: list/watch only the explicitly approved Kubernetes resource kinds and namespaces; no Secret access; no mutation verbs.
- AAP integration: separate identity; exact job-template allowlist; approval and change authorization required; no general-purpose inventory or arbitrary playbook execution.

## Data protection

- Never ingest Secret objects, private keys, tokens, kubeconfigs, environment variable values, raw MachineConfig file contents or webhook CA bundles.
- Strip `metadata.managedFields`, credentials in log messages, authorization headers, URL query secrets and sensitive labels where required.
- Apply bounded evidence excerpts and retention. Store hashes and source references rather than full raw payloads by default.
- Encrypt traffic and storage; rotate credentials; audit access and export; enforce PostgreSQL RLS where cluster/tenant partitioning requires it.

## Prompt-injection resistance

Treat log lines, event messages, annotations, labels, object fields, tickets and user-provided text as hostile content. Delimit them as evidence data; never concatenate them into system/developer instructions. No LLM-produced text may be passed to a shell. Command output is a recommendation template only and must be validated against typed schemas and command allowlists.

## Hard safety gates

- Runtime tool registry must fail startup if a mutation-capable Kubernetes, SSH, shell-write or AAP-launch tool is registered in diagnosis mode.
- Track B must force `playbook_match=false`, `playbook_id=null` and exploratory confidence.
- Missing evidence, stale telemetry, wrong-cluster records, contradictory evidence or version mismatch prohibit high-confidence supported diagnoses.
- High-risk actions (finalizer removal, force deletion, storage detach, VM shutdown, master/etcd restart, reboot, MachineConfig changes, webhook bypass) are never auto-launched.
