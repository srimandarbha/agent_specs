# Cluster Registry Contract

## Purpose

The cluster registry is the authoritative allowlist used before any evidence query. It is not a Kubernetes API proxy and contains no cluster credentials.

## Required record

- `cluster_id` (stable unique identifier)
- `cluster_name` and environment classification
- region/datacenter and owner/team
- supported OpenShift version range and current observed version
- enabled use cases and required evidence adapters
- Splunk tenant/index aliases and Prometheus tenant/cluster selectors
- timezone and incident routing metadata
- status (`active`, `maintenance`, `disabled`, `retired`)
- policy profile and data-retention class
- last inventory verification and registry revision

Never accept arbitrary query selectors from an event to override registry mappings. Reject unknown/disabled clusters before calling MCP. Do not store API tokens, kubeconfigs, client certificates or passwords in the registry.
