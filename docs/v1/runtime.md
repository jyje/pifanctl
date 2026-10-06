# v1 alpha runtime manual

**Implemented alpha, not a stable hardware release.** Application
`1.0.0-alpha.5` includes the portable schema/planner, freshness metric, guarded
worker, official Kubernetes client, operator, CLI and operator chart. Mock tests
do not establish real PWM behavior. [PLAN.md](../../PLAN.md) records the staged
checks and remaining release gates. [Korean](runtime-ko.md).

## 01: choose the physical topology

Use the [scenario figures](../../README.md#cooling-systems-manual-scenario-figures)
and [examples](../../design/v1/examples): two shared rack fans, per-board fans,
or several fans on one Node. One `Fan` is one actuator. One
`CoolingZone` selects cooled Nodes by labels or names and references its fans.
Shared fans use the union of all assigned zones plus their own local sensor.
There are no separate per-node member/worker CRDs.

```sh
PYTHONPATH=sources python sources/main.py topology validate design/v1/examples/two-racks.yaml
PYTHONPATH=sources python sources/main.py topology plan design/v1/examples/two-racks.yaml
# Selectors need live Node identity; this only reads the API:
pifanctl --context lab topology plan design/v1/examples/two-racks.yaml --live
```

`validate` checks shape and static relationships; `plan` preserves unresolved or
unhealthy relationships as explicit issues. Node objects must have Ready=True
to count as healthy. A complete explicit `v1/List` with `items: []` is valid
for retiring a topology. Empty files, duplicate keys, NaN and recursive aliases
are rejected. Pin/chip/channel/node are immutable for an existing Fan identity.
Release an old identity before reusing its channel with a new name.

Selector members removed from the Node API remain in the last expected set and
force full duty. A changed member Node UID is also retained as `NodeReplaced`,
since node-name-only telemetry cannot prove which physical board was replaced.
Review the rack inventory and replace the zone or explicitly change membership
to acknowledge the new identity. Live label edits can remove an existing Node
from membership intentionally. These guards survive operator restart in plans.

## 02: operator-managed workers

The v1 operator creates and owns workers on the Nodes selected by each `Fan`.
Users do not run an independent local PWM controller. This keeps the CRD state,
worker plan, and hardware writer under one Kubernetes reconciliation path.
`start` is not a v1 command. `worker run --file` requires `--mock`; hardware
workers require `--plan-file`, `--heartbeat-file`, and `--uid` supplied by the
operator. `worker run --mock` remains useful for isolated software development, but local
hardware control is outside the v1 product contract.

### Electrical fail-open requirements

`100%` is a requested PWM duty, not a measured voltage, fan RPM, or guarantee
that the fan has power. The signal state during process termination, board
reboot, disconnected wiring, or controller power loss depends on the actual Pi,
driver, fan input polarity, and external circuit. Do not assume a floating input
or a GPIO HIGH state means maximum cooling. Before using the system as a cooling
safety control, measure the signal and fan rotation on each supported hardware
combination and provide an independent, correctly rated fan supply. The fan
input must have a verified hardware default that requests the fan's safe maximum
when software no longer controls the signal. This project does not prescribe a
universal pull-up, pull-down, or polarity. Complete the [release acceptance
field manual](release-acceptance.pdf) and retain its measured evidence before a
stable release. A fan-supply or mechanical failure cannot be corrected by
software.

## 03: prepare Kubernetes

The alpha image is **not available merely because this PR exists**. Build and
publish it through the main pipeline after review, or supply a test image tag
that contains this code. Stable v1.0.0 still needs hardware acceptance.

```sh
helm lint charts/pifanctl-operator
helm template pifanctl charts/pifanctl-operator -n pifanctl-system
# On an explicitly selected review cluster after making the image available:
helm upgrade --install pifanctl charts/pifanctl-operator \
  -n pifanctl-system --create-namespace
pifanctl --context lab topology apply topology.yaml --dry-run
pifanctl --context lab topology apply topology.yaml
kubectl --context lab get fans,coolingzones
kubectl --context lab wait --for=condition=Ready fan/fan-01
```

The chart manages agents or reuses agents exporting
`pifanctl_temperature_observed_timestamp_seconds`. Prometheus must scrape **each
agent endpoint**, retain its `node` identity, and expose the API URL configured
in each zone. A single Service scrape against one backend is insufficient.
Enable ServiceMonitor only if the Prometheus Operator CRD and selectors exist;
otherwise configure per-Pod/Endpoint scraping. Old agents without read-time
metrics make remote zones unhealthy and request full duty.

Helm installs CRDs but does not upgrade them. Review and apply
`charts/pifanctl-operator/crds/` explicitly for future schema upgrades. Use
`charts/pifanctl-operator` to install the runtime and render instances through
`extraResources`. Keep these values in the GitOps Application. The design chart
is not a supported v1 installation path.

## 04: CR instances and kubectl CLI

```sh
pifanctl --kubeconfig ./lab.config --context lab fan list
pifanctl --context lab zone describe rack-a
pifanctl --context lab fan watch
kubectl pifanctl --context lab fan list
```

Declare the cluster's `Fan` and `CoolingZone` objects in the operator chart's
`extraResources` values. The chart installs their CRDs and submits the instance
resources. For Argo CD, put the array in the operator Application's Helm values
and let GitOps own changes. `install.sh` installs `kubectl-pifanctl`, which
delegates to the same kubeconfig-aware inspection CLI. CLI `topology apply` uses
server-side apply with `fieldManager=pifanctl-cli`, `force=false`; `--dry-run`
sends `dryRun=All`. Apply is not transactional across several resources. For
Helm/GitOps, edit the authoritative source instead of forcing managed-field
ownership.

### Curve and temperature hysteresis

`spec.control.curve` of a Fan maps the hottest assigned temperature to a duty. The
fields are `temperatureLow`, `temperatureHigh`, `dutyIdle`, `dutyStart`, `dutyMax`,
`dutyDownStep` and `temperatureHysteresis`.

`temperatureHysteresis` (default `5`, in degrees Celsius) is how far the temperature
must fall below its peak before the duty follows it down. The fan starts at
`temperatureLow` but only stops once the temperature is `temperatureHysteresis` below
that peak, so a fan that cools its own zone below the start point does not switch on
and off repeatedly. Rising temperatures are never delayed. Set `0` to turn it off. It
must be below `temperatureHigh - temperatureLow`, which the CRD and the planner both
enforce. `dutyDownStep` is separate: it limits how fast the duty falls once it may.

For graphs, a worked example and advice on the value, see
[Temperature hysteresis](../hysteresis.md).

## 05: verify convergence and failures

The operator renews a 30-second Lease before mutations. Node/CR watches wake
reconciliation; a five-second full resync recovers disconnects and detects
ConfigMap/workload/report changes. CR lists and Node lists are separate API
snapshots, not a transaction; cross-object changes may temporarily request full
duty. Operators claim CR metadata and refuse another operator's ownership.
One worker Deployment per actuator Node has Recreate/replicas=1, required name
and actual hostname affinity, and a plan containing Node UID. Workers have no
Kubernetes credentials. Leader loss stops heartbeat refresh.

CR-mode ownership records `namespace/operatorId`, so an identical ID in another
namespace cannot adopt the same CRs. This alpha uses one CR-mode installation
for the cluster-wide topology; replicas share its Lease. The alpha chart defaults
to one operator and uses Recreate for replacement because only the leader is
Ready. Worker heartbeat expiry remains active during replacement. Multi-replica
readiness and upgrade availability require further work.

ConfigMap directory projection can lag. The worker checks separate plan and
heartbeat files, matching hash and UID, allowing at most five seconds future
skew. **Watchdog default: 120 seconds**, chosen to tolerate common projection
delay; measure your environment. Projection lag can legitimately trigger full
duty. A healthy heartbeat does not bypass a zone's missing/stale sensor input.
The worker only decreases duty on each fan's refresh interval; rising demand
and failures are applied immediately when sampled.

A separate worker thread checks heartbeat expiry and control-loop progress every
second, independently of Prometheus queries. Its full-duty latch cannot be
overridden by a late query; the main loop must revalidate before clearing it.

| Observation | Meaning |
| --- | --- |
| `/status`, `/metrics` on worker :9103 | Applied hash, requested duty, member temperatures and reasons |
| `/healthz` | Process HTTP endpoint alive, not proof of cooling |
| `/readyz` | All desired fans are currently regulating safely; unhealthy returns 503 |
| Fan/CoolingZone `status.conditions[Ready]` | Fresh worker report with matching hash/UID and healthy inputs |
| Operator :9104 | `/healthz`, `/readyz`, `/metrics`; only the Lease leader is ready |

Reports must be at most 90 seconds old. Steady-state status writes are capped at
one per 30 seconds per object; readiness/reason/config changes are immediate.
Events are emitted on transitions and limited per reason in each process.
Cluster scoped CR Events live in `default`; the chart grants only Event creation
in that namespace. Event API failures are logged and retried without blocking
heartbeat renewal.
The alpha implements one Ready condition with detailed reasons; additional
diagnostic conditions and stock alert rules remain future enhancements.
Metrics contain node/fan/zone labels, never a stream of config-hash labels.
Duty is requested PWM, not RPM. The system does not detect a mechanically stuck
fan or guarantee power-loss cooling.

### Scrape safety state

Enable the chart's `serviceMonitor.enabled` and configure its selector labels
and monitoring namespace NetworkPolicy. The worker Service includes unready
endpoints, so `pifanctl_worker_fan_ready == 0` remains visible during failsafe.
Both reused-agent and managed-agent installations get a worker ServiceMonitor.
Migrate legacy controller alerts/dashboard queries to worker duty/readiness
metrics explicitly; preserve temperature alerts and monitor scrape failures.
Scope absent-series alerts to the intended installation or fan inventory.

## 06: retire and migrate

Remove zones/Fans while the operator remains running.
For Argo CD, remove them from the desired `extraResources` configuration rather
than issuing a direct delete that self-heal could recreate. Use
`PrunePropagationPolicy=background` and `PruneLast=true`, and follow the
[staged Application example](../../design/v1/examples/argocd.yaml). Set
`extraResources: []` and wait for all installation CRs and workers to retire
before removing the operator Application. Include any CRs created by CLI in
this inventory. Shared CRDs are retained during automatic prune/deletion.
Use `kubectl delete ... --cascade=background` (the default). Foreground garbage
collection can remove owned workers before the release acknowledgement and
leave the application's finalizer pending; it is not a supported retirement path
in this alpha. It publishes replacement plans and waits for matching worker acknowledgements.
A fan with no zone stays at 100%. Removing a Fan drives full duty, closes its
driver, and acknowledges a plan without that fan. For the last fan, the worker
Deployment is deleted and Pods must disappear before finalization. Empty-plan
acknowledgements survive operator restart in the ConfigMap until owner GC.
If other fans remain on the same Node, ownership transfers first. Unreachable
workers leave finalizers pending. A forced finalizer removal proves no hardware
safety and must be an explicit administrator decision.

Inventory wiring, compare a read-only plan, leave full duty, stop old v0 writers,
verify the processes are gone, then start the alpha on **one actuator host at a
time**. Roll back by stopping the alpha and releasing its lock before restoring
the legacy controller. Do not uninstall the operator before resources finish
release. Node/power loss, real Pi 4/Pi 5 PWM, server CEL/defaulting and fleet load
remain acceptance gates in PLAN.md. Live deployment requires an explicitly authorized trial and an archived rollback plan.

## Runtime compatibility with legacy cluster CAs

Python 3.13+ enables stricter X.509 validation that can reject a legacy cluster
CA missing required extensions. Keep certificate and hostname verification
enabled. An isolated experimental image can use the supported Python 3.12
runtime while CA modernization is planned separately:

```sh
gh workflow run build-image-issue.yaml --ref YOUR_BRANCH -f python-version=3.12
```

That image uses `ghcr.io/jyje/pifanctl-issue:<sha>-py312`; it cannot publish
`latest` or release tags. Set the operator chart's image repository/tag to the
published variant and verify operator readiness before assigning a physical Fan.
The default image remains Python 3.14, and CI still tests Python 3.10-3.14.
See the [Python SSL documentation](https://docs.python.org/3/library/ssl.html#ssl.create_default_context).

## CRD API versions

The candidate serves `v1` with `v1alpha1` compatibility. Read the [storage migration and rollback procedure](api-migration.md) before upgrading an existing installation.
