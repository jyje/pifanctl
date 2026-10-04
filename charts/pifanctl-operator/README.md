# pifanctl operator chart (alpha)

This chart deploys the v1 operator and optional temperature agents. Workers are
created by the operator for physical actuator Nodes. The alpha image must be
built and published before installation; a PR does not create a registry image.

See [English runtime instructions](../../docs/v1/runtime.md),
[Korean](../../docs/v1/runtime-ko.md) and the [implementation checklist](../../PLAN.md).

```sh
helm lint charts/pifanctl-operator
helm template pifanctl charts/pifanctl-operator -n pifanctl-system
# Only after choosing a disposable cluster and making the alpha image available:
helm upgrade --install pifanctl charts/pifanctl-operator \
  -n pifanctl-system --create-namespace
```

| Value | Purpose |
| --- | --- |
| `operatorId` | Short, unique identity; another operator cannot adopt its CRs |
| `replicas` | 2 replicas by default, one active Lease holder |
| `input.mode` | `crd` or `configMap` |
| `input.configMapName` | Existing input ConfigMap in the release namespace |
| `agent.mode` | `managed` or `reuse`; reused agents must export read timestamps |
| `image.tag` | Defaults to pinned `v1.0.0-alpha.1`; never `latest` |
| `networkPolicy.monitoringNamespaceSelector` | Namespaces allowed to read worker metrics/status |
| `serviceMonitor.enabled` | Create worker and managed-agent ServiceMonitors if Prometheus Operator is installed |

CRDs in `crds/` are installed by Helm, but Helm does not upgrade or delete them.
Review and apply schema upgrades explicitly. ConfigMap mode can use
`--skip-crds`; its operator RBAC only needs Node cluster reads. Namespace-scoped
permissions create workloads/config, publish Events and update the Lease. CR
mode additionally patches topology metadata/status, never user specs. Cluster scoped
CR Events are written in `default` using an additional Role granting only Event
creation there. Event publication failure is logged and retried without blocking
heartbeat renewal. There is
no Secret read, Node label write, namespace creation or CRD write permission.

Worker Pods are privileged/root with `/sys`, `/dev` and a shared host lock.
Operator/agents are non-root and receive no hardware access. Workers/agents have
no Kubernetes token. Privileged workloads need an explicitly suitable namespace
Pod Security policy. NetworkPolicy requires a CNI that enforces it. Ingress is
restricted; worker egress must reach DNS and the configured Prometheus endpoint.
Specify image digests via `image.tag` is not supported: use an immutable version
tag here; digest-based image configuration is a future packaging enhancement.

Delete Fans/zones/input configuration while the operator is still running and
wait for finalizers before uninstalling. An unreachable worker deliberately
blocks deletion. Never delete CRDs or force finalizers to claim hardware safety.

## Monitoring migration

Worker metrics use `pifanctl_worker_fan_duty_percent` and
`pifanctl_worker_fan_ready`, labeled by node and fan. The headless worker Service
publishes unready endpoints so failsafe metrics remain scrapeable. Set
`serviceMonitor.enabled=true`, the monitoring selector labels, and
`networkPolicy.monitoringNamespaceSelector` for your Prometheus installation.
This works with reused agents as well as chart-managed agents.

Existing v0 controller alerts and dashboard queries need explicit migration.
Preserve the agent temperature alerts, replace controller-duty absence checks
with worker metrics, and alert on `pifanctl_worker_fan_ready == 0` plus scrape
failures. An absent-series check should be scoped to the expected installation
or fan inventory. Requested duty does not prove measured fan RPM.
