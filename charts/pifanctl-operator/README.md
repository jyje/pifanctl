# pifanctl operator chart (alpha)

This chart deploys the v1 operator and optional temperature agents. Workers are
created by the operator for physical actuator Nodes. The alpha image must be
built and published before installation; a PR does not create a registry image.

See [English runtime instructions](../../docs/v1/runtime.md),
[한국어](../../docs/v1/runtime-ko.md) and the [implementation checklist](../../PLAN.md).

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
| `serviceMonitor.enabled` | Create agent ServiceMonitor if Prometheus Operator is installed |

CRDs in `crds/` are installed by Helm, but Helm does not upgrade or delete them.
Review and apply schema upgrades explicitly. ConfigMap mode can use
`--skip-crds`; its operator RBAC only needs Node cluster reads. Namespace-scoped
permissions create workloads/config, publish Events and update the Lease. CR
mode additionally patches topology metadata/status, never user specs. There is
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
