# Migration 002 Notes

`002_agent_contracts.sql` is additive. Review it against the deployed PostgreSQL version and the actual grants before applying.

Important: the database cannot enforce the full separation of agent, approver and AAP integration by comments alone. Create separate roles and column/table grants in deployment-specific SQL. The agent runtime must not update approval or external execution fields. Historical `kubernetes_api` evidence rows are retained, but the no-Kubernetes-API deployment profile must reject that adapter in application configuration and tests.

The original `execution_allowed = false` check remains unchanged. A recommendation record does not grant execution permission.
