# Security Review Checklist

- [ ] Agent runtime has no Kubernetes API token, client certificate, kubeconfig, write-capable tool, SSH credential or AAP launch credential.
- [ ] Collector RBAC is read-only and limited to enabled resource kinds; Secrets are not listable/watchable.
- [ ] Splunk/Prometheus access is query-only and cluster-scoped.
- [ ] Cluster registry prevents arbitrary cluster/query-target selection.
- [ ] Kafka/HTTP producers are authenticated; schema and size limits are enforced.
- [ ] Credentials, env values, MachineConfig content, webhook CA bundles and sensitive log fields are redacted.
- [ ] PostgreSQL runtime, migration, approval and AAP roles are separate; column-level permissions are tested.
- [ ] RLS/tenant isolation is tested where required.
- [ ] Tool registry rejects mutation-capable tools at startup.
- [ ] Prompt-injection tests cover logs, annotations, Events, labels, manual requests and ticket text.
- [ ] Track B cannot produce a playbook ID or automated action.
- [ ] Human approvals bind to exact cluster/target/playbook/variables hash and expire.
- [ ] Audit logs capture investigation, approval and external execution transitions.
- [ ] Backup, retention, deletion, restore and credential rotation are tested.
