<div align="center">

# pifanctl: Raspberry Pi Cluster Fan Control, the Kubernetes Way

<img alt="Cartoon Raspberry Pi rack with one shared PWM fan and a Kubernetes whale mascot" src="docs/pifanctl-cluster-sticker-concept-1.png" width="560" style="object-fit: contain; max-width: 100%;">

🥧 One board or a rack. Declare the fans. Follow the hottest member.

[![Python Typer](https://img.shields.io/badge/Typer-3776AB?style=flat&logo=Python&logoColor=white&label=Python)](https://typer.tiangolo.com/)
[![GitHub ARC](https://img.shields.io/badge/GitHub%20ARC-2088FF?style=flat&logo=GitHub%20Actions&logoColor=white&label=CI)](https://github.com/actions/actions-runner-controller)
[![CLI](https://img.shields.io/badge/CLI-orange?style=flat&logo=Typer&logoColor=white)](https://typer.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=Docker&logoColor=white)](https://docker.io)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-326CE5?style=flat&logo=Kubernetes&logoColor=white)](https://kubernetes.io)<br/>
[![CI status for pull requests](https://github.com/jyje/pifanctl/actions/workflows/ci.yaml/badge.svg)](https://github.com/jyje/pifanctl/actions/workflows/ci.yaml)
[![CI status for main branch](https://github.com/jyje/pifanctl/actions/workflows/build-image-main.yaml/badge.svg?branch=main)](https://github.com/jyje/pifanctl/actions/workflows/build-image-main.yaml)
[![CI status for develop branch](https://github.com/jyje/pifanctl/actions/workflows/build-image-develop.yaml/badge.svg?branch=develop)](https://github.com/jyje/pifanctl/actions/workflows/build-image-develop.yaml)
[![Codecov coverage](https://codecov.io/gh/jyje/pifanctl/branch/main/graph/badge.svg)](https://app.codecov.io/gh/jyje/pifanctl)
[![GitHub Repo stars](https://img.shields.io/github/stars/jyje/pifanctl?style=flat&color=yellow&label=%F0%9F%8C%9F%20Stars)](https://github.com/jyje/pifanctl)

**English** | [Korean](README-ko.md)

</div>

🐳 **pifanctl** (Pi Fan Control) manages PWM fans for Raspberry Pi cooling zones through Kubernetes. A zone can contain a single board, four boards sharing one rack fan, or several racks with separate fans. Declare `Fan` actuators and `CoolingZone` membership by Node labels or names. Each fan follows the hottest assigned member plus its local sensor. The operator creates one hardware worker per actuator Node; temperature agents report to Prometheus.

**v1:** CRDs and the single operator chart are required. Standalone `start` control is removed. Local YAML worker execution requires `--mock`; real workers consume the operator's plan, Node UID, and heartbeat. The `1.0.0` release proposal follows the approved practical verification closeout. See the [release scope and limitations](CHANGELOG.md) and [release plan](PLAN.md); proposed artifacts are not available until publication.

The sticker depicts an abstract Raspberry Pi rack, rear-facing board ports, a shared front fan, and a Kubernetes whale mascot. [Illustration style and concepts](docs/illustration-style.md).

| Component | Role |
| --- | --- |
| Fan CR | One physical actuator, its Node, hardware channel, curve, and failsafe policy |
| CoolingZone CR | Nodes to cool and the fans assigned to them |
| Operator | Resolves membership, claims channels, and reconciles workers and status |
| Worker | Controls the fans on its Node from the operator plan and fresh telemetry |
| Agent and Prometheus | Export and retain per-node temperature and source timestamps |

## 1. Install and declare cooling instances

Requirements: Kubernetes, ARM64 Raspberry Pi actuator Nodes, reachable Prometheus, and verified fan wiring. The live campaign used Pi 4 shared-fan actuation and a Pi 5 CPU-load/temperature member. Pi 5 sysfs actuation has mock coverage; physical validation is deferred. See [follow-up #64](https://github.com/jyje/pifanctl/issues/64).

Copy and customize the [operator values example](tests/fixtures/operator-extra-resources.yaml). Its `pi-01` Node and rack labels are illustrative and must match your hardware inventory. Declare instances in the chart's `extraResources` array. For a single board, use a one-member CoolingZone and one Fan on that Node.

```sh
# Select the intended Kubernetes context and a published, reviewed image.
helm upgrade --install pifanctl charts/pifanctl-operator \
  --kube-context lab --namespace pifanctl-system --create-namespace \
  -f cooling-values.yaml
kubectl --context lab get fans,coolingzones
kubectl --context lab wait --for=condition=Ready fan/rack-fan-01 --timeout=120s
```

For a legacy cluster CA, the stable Python 3.12 compatibility image uses `image.tag: v1.0.0-py312`; the default is canonical Python 3.14. Keep TLS verification enabled and follow the [runtime compatibility procedure](docs/v1/runtime.md#runtime-compatibility-with-legacy-cluster-cas).

The chart pins its own image version. An application release does not automatically update that pin. Verify image availability before installation. Helm installs CRDs on first install; review and explicitly apply schema upgrades as described in the [runtime manual](docs/v1/runtime.md). Argo CD users keep the chart values and `extraResources` in their Application, as in [jyje/cluster](https://github.com/jyje/cluster/blob/main/clusters/r4spi/apps/pifanctl.yaml).

### CLI and kubectl

```sh
# Install the inspection CLI and kubectl plugin.
./install.sh --mock
pifanctl --context lab fan list
kubectl pifanctl --context lab zone describe rack-a
pifanctl topology validate design/v1/examples/two-racks.yaml
pifanctl --context lab topology plan topology.yaml --live
pifanctl --context lab topology apply topology.yaml --dry-run
```

The local CLI manages Kubernetes resources. `topology apply` uses server-side apply without forced ownership. Edit GitOps-managed instances in their source repository. `status` reads local temperatures; `agent` publishes metrics. Neither controls a fan. Local mock development is documented in the runtime manual.

### Cooling behavior and observability

A fan uses the maximum temperature across all assigned zones and its local sensor. Missing or stale required input and expired operator heartbeat request failsafe duty. Temperature hysteresis delays falling duty; rising demand is applied immediately. These are PWM requests, not measured RPM or guarantees of fan power. See [curve hysteresis](docs/hysteresis.md), [runtime metrics and retirement](docs/v1/runtime.md), and the [acceptance manual](docs/v1/release-acceptance.md).

Retain per-agent samples in Prometheus and scrape every agent endpoint with its Node identity. Enable chart ServiceMonitors only when the Prometheus Operator CRDs and selectors exist. The operator chart does not install Prometheus or the legacy controller dashboards. Retire all old writers and preserve the rollback archive before enabling v1 hardware workers.

Historical standalone commands and the old chart belong to the [v0 usage archive](docs/legacy/v0-usage.md).

## 2. Develop and verify

Python 3.10+ and Helm are required for the full software suite. Install dependencies into a project virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r sources/requirements.dev.txt
.venv/bin/python -m pytest --cov=sources --cov-branch --cov-report=xml
PYTHONPATH=sources .venv/bin/python sources/main.py --help
```

Tests use simulated sensors and drivers. They do not certify electrical hardware. [Coverage policy and Codecov](docs/testing/coverage.md) describe CI reports and line/branch measurements.

## 3. CI/CD Pipeline

This project uses [GitHub Actions with Actions Runner Controller (ARC)](https://github.com/actions/actions-runner-controller) for ARM64-based CI/CD pipeline. The builds are executed on self-hosted Raspberry Pi runners, ensuring native ARM64 compatibility.

You can check the environment of CI/CD pipeline in [app.jyje.online#stack](https://app.jyje.online/#stack)

### 3.1. Workflow Structure

| Workflow | Trigger | What it does |
| --- | --- | --- |
| `ci` | every pull request | Lints the workflows, runs tests on every stable Python minor release from 3.10 through 3.14, lints and schema-validates the chart (kubeconform, `promtool`), and builds the ARM64 image on the in-cluster runner without pushing |
| `build-image-main` | push to `main` | Publishes the commit SHA tag and `v<version>` (once per version); stable versions also update `latest` |
| `build-image-develop` | push to `develop` | Publishes `ghcr.io/jyje/pifanctl-dev:latest` and the SHA tag |
| `build-image-issue` | push to `issue-**` | Publishes `ghcr.io/jyje/pifanctl-issue:<sha>` for temporary testing |
| `release-chart` | push to `main` touching `charts/pifanctl-operator/` | Publishes the supported v1 operator chart to `oci://ghcr.io/jyje/charts/pifanctl-operator` |

The three image workflows share one reusable workflow, `_build-image.yaml`.

### 3.2. Key Features

- Native ARM64 builds using self-hosted runners (**`r4spi-microk8s`**, an [ARC](https://github.com/actions/actions-runner-controller) runner scale set in the cluster). Pull requests from forks never run on it
- Skip CI option with **`--no-ci`** in a commit message, evaluated by the workflow engine and never interpolated into a shell script
- GitHub Container Registry (ghcr.io) integration, with immutable `v<version>` tags
- The built image is tested: it prints its version, runs unprivileged, and refuses to start the real GPIO driver where there is no GPIO

### 3.3. Releasing

Application and chart versions are tracked separately. A pull request that changes what ships has to bump the relevant versions:

| Changed | Bump | Checked by |
| --- | --- | --- |
| `sources/main.py` or `sources/pifanctl/` | `__version__` in `sources/pifanctl/__init__.py` | the `Version bump` job |
| A chart directory (not its `ci/` value sets) | `version` in that chart's `Chart.yaml`; chart versions are independent from the application and other charts | the `Version bump` job |

The operator chart's `appVersion` pins its default image. Updating that pointer changes chart content and requires a chart version bump. An app-only release does not force a chart release.

Merging to `main` does the rest:

1. `build-image-main` publishes the commit tag and `v<version>` the first time a version appears. Stable versions also update `latest`; alpha versions leave it unchanged.
2. After the image exists, it creates the git tag `v<version>` and a GitHub release with generated notes.
3. When the operator chart changes, `release-chart` waits for the image pinned by that chart's `appVersion`, publishes only `pifanctl-operator`, and creates an `operator-chart-v<version>` tag and release.

Each step skips what already exists, so re-running a failed workflow is safe. Application releases are tagged `v*`; the supported operator chart uses `operator-chart-v*`. Alpha versions are GitHub prereleases.

---
## 4. Runtime and cooling scenarios

[Runtime manual](docs/v1/runtime.md), [operator design](docs/v1/README.md), [CRDs and examples](design/v1/README.md), and [release checklist](PLAN.md).

#### Cooling systems manual: scenario figures

Example temperatures illustrate the v1 model. Figures show steady-state target duty; the downward ramp is omitted. These are not hardware measurements.

![Shared rack fans in normal operation](docs/v1/figures/rack-normal-en.png)

<details>
<summary>NORMAL: one fan per board</summary>

Each fan follows its own board.

![Per-board fans: normal](docs/v1/figures/individual-normal-en.png)

</details>

<details>
<summary>HIGH TEMPERATURE: pi-03 heats up</summary>

A hot member drives its assigned fan to full duty. Other cooling zones are unaffected.

![Shared rack fans: hot](docs/v1/figures/rack-hot-en.png)

![Per-board fans: hot](docs/v1/figures/individual-hot-en.png)

</details>

<details>
<summary>DATA LOST: pi-03 stops reporting</summary>

An incomplete shared zone forces its fan to 100%. With per-board fans, only the missing board's fan enters failsafe.

![Shared rack fans: missing](docs/v1/figures/rack-missing-en.png)

![Per-board fans: missing](docs/v1/figures/individual-missing-en.png)

</details>

<details>
<summary>WATCHDOG EXPIRED: operator heartbeat lost</summary>

Expired operator heartbeat forces every affected worker to hold its fans at 100%.

![Shared rack fans: watchdog](docs/v1/figures/rack-watchdog-en.png)

![Per-board fans: watchdog](docs/v1/figures/individual-watchdog-en.png)

</details>

[SVG originals and rendering instructions](docs/v1/figures/README.md).


---
## 5. References

- [Official: Raspberry Pi Foundation](https://www.raspberrypi.org)
- [Blog: Using Raspberry Pi to Control a PWM Fan and Monitor its Speed](https://blog.driftking.tw/en/2019/11/Using-Raspberry-Pi-to-Control-a-PWM-Fan-and-Monitor-its-Speed/)
