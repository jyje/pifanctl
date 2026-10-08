# pifanctl operator chart

This is the single supported pifanctl chart for v1. It installs the CRDs,
operator, temperature agents, and the managed workers created for physical
actuator Nodes. Declare the cluster's `Fan` and `CoolingZone` custom resources
in `extraResources`; the chart submits them alongside the runtime. Standalone
fan control and ConfigMap topology input are outside the v1 contract.

See [English runtime instructions](../../docs/v1/runtime.md),
[Korean](../../docs/v1/runtime-ko.md) and the [implementation checklist](../../PLAN.md).

```sh
helm lint charts/pifanctl-operator
helm template pifanctl charts/pifanctl-operator -n pifanctl-system
# Add Fan and CoolingZone instances through valuesObject.extraResources in GitOps.
# Only after choosing a disposable cluster and making the pinned image available:
helm upgrade --install pifanctl charts/pifanctl-operator \
  -n pifanctl-system --create-namespace
```

| Value | Purpose |
| --- | --- |
| `operatorId` | Short, unique identity; another operator cannot adopt its CRs |
| `replicas` | 1 by default; only the active Lease holder is Ready |
| `agent.mode` | `managed` or `reuse`; reused agents must export read timestamps |
| `image.tag` | Defaults to pinned `v1.1.0`; never `latest` |
| `extraResources` | Kubernetes resources submitted with the release; use `Fan` and `CoolingZone` CRs for the cooling topology |
| `networkPolicy.monitoringNamespaceSelector` | Namespaces allowed to read worker metrics/status |
| `serviceMonitor.enabled` | Create worker and managed-agent ServiceMonitors if Prometheus Operator is installed |

The canonical default uses Python 3.14. For the documented legacy-CA path, select
`image.tag: v1.1.0-py312` explicitly and retain TLS verification. The app version
is still 1.1.0. See [runtime compatibility](../../docs/v1/runtime.md#runtime-compatibility-with-legacy-cluster-cas).

Example values for a shared rack fan:

```yaml
extraResources:
  - apiVersion: pifanctl.jyje.online/v1
    kind: Fan
    metadata:
      name: rack-fan-01
    spec:
      nodeName: raspi-40
      hardware:
        rpigpio: {pin: 18, frequencyHz: 1000}
      control:
        curve:
          temperatureLow: 50
          temperatureHigh: 70
          dutyIdle: 0
          dutyStart: 30
          dutyMax: 100
          dutyDownStep: 5
        refreshIntervalSeconds: 5
        failsafeDuty: 100
        exitDuty: 100
  - apiVersion: pifanctl.jyje.online/v1
    kind: CoolingZone
    metadata:
      name: rack-a
    spec:
      fanRefs: [rack-fan-01]
      telemetry:
        source: prometheus
        prometheusURL: http://prometheus-operated.monitoring.svc:9090
        maxSampleAgeSeconds: 30
      nodeSelector:
        matchLabels:
          pifanctl.jyje.online/rack: a
```

For Argo CD, place this array in the operator Application's Helm values. Keep the
CR instances in GitOps and update them through the Application source.

CRDs in `crds/` are installed by Helm, but Helm does not upgrade or delete them.
The shared definitions also carry Argo CD `Prune=false,Delete=false` annotations
so automatic pruning or Application deletion cannot remove the cluster-wide API.

Operator replacement uses `Recreate` because leader-only readiness would block
a surge rollout. The worker keeps its last plan during operator replacement and
requests failsafe duty if the heartbeat expires. Multi-replica readiness and
availability during operator upgrades remain follow-up work; one replica is the supported configuration.

Review and apply schema upgrades explicitly. Namespace-scoped permissions create
workloads/config, publish Events and update the Lease. The operator patches CR
metadata/status, never user specs. Cluster scoped
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

Remove Fans/zones from their desired configuration while the operator is still
running and wait for finalizers before uninstalling. An unreachable worker
deliberately blocks deletion. Never delete CRDs or force finalizers to claim
hardware safety.

## Argo CD lifecycle

Use the [declarative Application example](../../design/v1/examples/argocd.yaml).
Pin a published chart release tag or immutable commit. Configure
`PrunePropagationPolicy=background` and `PruneLast=true`: foreground pruning is
not a supported claim-retirement path because garbage collection
can remove a worker before its release acknowledgement.

Remove retired Fans from zone references and `extraResources` in the desired
GitOps configuration, then let Argo CD synchronize and prune. For complete
retirement, set `extraResources: []` first. Inventory CLI-created CRs belonging
to this installation as well; an empty array alone does not prove they are gone.
Wait for all associated Fan/CoolingZone finalizers, worker Deployments and Pods
to disappear while the operator remains Ready. Only then delete the operator
Application. The CRDs remain installed with their UIDs intact for other
installations and future reinstallations.

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

When migrating an existing operator Deployment from RollingUpdate with
server-side apply, remove its old rollingUpdate settings atomically before
synchronizing the new chart:

```sh
kubectl -n YOUR_NAMESPACE patch deployment YOUR_RELEASE-operator \
  --type=merge -p '{"spec":{"strategy":{"type":"Recreate","rollingUpdate":null}}}'
```

This replaces operator Pods; the worker retains its plan and heartbeat failsafe.

## Optional RPM feedback (1.1.0)

Existing values remain compatible. Add `spec.feedback.tachometer` to an existing
Fan in `extraResources` only when its input wiring has been verified. Omitting
feedback allocates no input and leaves PWM behavior unchanged. See the comments
in [values.yaml](values.yaml), the [complete values fixture](../../tests/fixtures/operator-tachometer-values.yaml),
and the [tachometer guide](../../docs/v1/tachometer.md) for defaults, Pi 4 backend
limits, metrics and explicit CRD upgrade/rollback steps.

Chart `version` and `appVersion` follow the application version, starting with
1.1.0. An empty `image.tag` uses `v1.1.0`; explicit image overrides remain valid.
The proposed 1.1.0 artifacts must be published before deployment.
