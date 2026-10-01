<div align="center">

# pifanctl: A Raspberry Pi Fan Controller

**English** | [한국어](README-ko.md)

<img alt="pifanctl logo" src="docs/whale-cooling-pie.jpg" width="450" style="object-fit: contain; max-width: 100%; aspect-ratio: 16 / 9;">

🥧 A CLI for **PWM Fan Controlling** of **Raspberry Pi**

[![Python Typer](https://img.shields.io/badge/Typer-3776AB?style=flat&logo=Python&logoColor=white&label=Python)](https://typer.tiangolo.com/)
[![GitHub ARC](https://img.shields.io/badge/GitHub%20ARC-2088FF?style=flat&logo=GitHub%20Actions&logoColor=white&label=CI)](https://github.com/actions/actions-runner-controller)
[![CLI](https://img.shields.io/badge/CLI-orange?style=flat&logo=Typer&logoColor=white)](https://typer.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=Docker&logoColor=white)](https://docker.io)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-326CE5?style=flat&logo=Kubernetes&logoColor=white)](https://kubernetes.io)<br/>
[![CI status for pull requests](https://github.com/jyje/pifanctl/actions/workflows/ci.yaml/badge.svg)](https://github.com/jyje/pifanctl/actions/workflows/ci.yaml)
[![CI status for main branch](https://github.com/jyje/pifanctl/actions/workflows/build-image-main.yaml/badge.svg?branch=main)](https://github.com/jyje/pifanctl/actions/workflows/build-image-main.yaml)
[![CI status for develop branch](https://github.com/jyje/pifanctl/actions/workflows/build-image-develop.yaml/badge.svg?branch=develop)](https://github.com/jyje/pifanctl/actions/workflows/build-image-develop.yaml)
[![GitHub Repo stars](https://img.shields.io/github/stars/jyje/pifanctl?style=flat&color=yellow&label=%F0%9F%8C%9F%20Stars)](https://github.com/jyje/pifanctl)


</div>

🐳 **pifanctl** is a CLI tool for PWM fan control on Raspberry Pi, from a single board to a whole cluster. It runs as a plain CLI, in **Docker**, or on **Kubernetes** with a Helm chart, and is optimized for ARM64. In a cluster the fans follow the **hottest node**, and every node's temperature is kept in Prometheus. The project features a CI/CD pipeline using GitHub Actions with Actions Runner Controller (ARC), ensuring all builds are tested in actual Raspberry Pi environments. Please enjoy it!


```mermaid
flowchart LR
  subgraph nodes["every node"]
    A1["agent<br/>(DaemonSet)"]
  end
  A1 -- "pifanctl_temperature_celsius{node}" --> P[("Prometheus<br/>(retention)")]
  P -- "max by (node)" --> C["controller<br/>(node with the fan)"]
  C -- "PWM duty" --> F(("fan"))
  P --> G["Grafana dashboard<br/>and alerts"]
```

| | Single board | Cluster |
| --- | --- | --- |
| Reads | its own thermal zones | every node, through Prometheus |
| Drives the fan from | its own temperature | the hottest node |
| History | none | kept in Prometheus, with a dashboard and alerts |
| Install | `install.sh`, Docker, raw manifest | Helm chart |

> **Status.** Cluster mode runs on a Raspberry Pi 4 cluster with the RPi.GPIO driver. The kernel PWM driver for Raspberry Pi 5 is covered by tests against a fake sysfs tree, but has not been run on a Pi 5 with a fan yet.

---
## 1. Run

### 1.1. Requirements

- Raspberry Pi (ARM64)
- Python 3.10+

You should access the Raspberry Pi (ARM64) to run the following commands.

### 1.2. OPTION 1: Install CLI like a package

```sh
curl -fsSL https://raw.githubusercontent.com/jyje/pifanctl/main/install.sh -o install-pifanctl.sh
chmod +x install-pifanctl.sh
./install-pifanctl.sh
rm install-pifanctl.sh

## Uninstall
# rm -rf $HOME/.pifanctl
```

After installation, run `pifanctl --help`:

```
 Usage: pifanctl [OPTIONS] COMMAND [ARGS]...

 🥧 pifanctl: A CLI for PWM Fan Controlling of Raspberry Pi

 Run `agent` on every node to publish temperatures, and `start` on the node
 that has the fan. With `--source prometheus` the fan follows the hottest
 node of the cluster.

╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ status  Show current temperatures                                            │
│ agent   Publish this node's temperatures as Prometheus metrics               │
│ start   Start fan control                                                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

Driving the pin needs root, so start the controller with `sudo pifanctl start`. `pifanctl status` and `pifanctl agent` do not.

### 1.3. OPTION 2: Using Docker
```sh
docker run --rm -it ghcr.io/jyje/pifanctl:latest python main.py --help
```

To start the fan:

```sh
docker run --privileged --user 0 -it ghcr.io/jyje/pifanctl:latest python main.py start
```

```
INFO [2026-10-01 14:30:00Z] Detected 'Raspberry Pi 4 Model B Rev 1.5', using the RPi.GPIO driver
INFO [2026-10-01 14:30:00Z] Controller started with driver 'rpigpio', interval 5.0s
INFO [2026-10-01 14:30:00Z] Duty: 36.6%, Temperature: 51.9°C, Following: raspberrypi, Source: local, Nodes: raspberrypi=51.9*
```

Controlling the pin needs access to GPIO and `/dev/mem`, so `start` needs `docker run --privileged --user 0`. The `agent` and `status` commands run unprivileged, and the image runs as a non-root user by default.


### 1.4. OPTION 3: On Kubernetes with Helm (recommended)

```sh
kubectl label node <the-node-with-the-fan> pifanctl.jyje.online/fan=true

helm install pifanctl oci://ghcr.io/jyje/charts/pifanctl --version 0.1.2 \
  --namespace pifanctl --create-namespace \
  --set prometheus.url=http://prometheus-operated.monitoring.svc:9090 \
  --set monitoring.serviceMonitor.enabled=true \
  --set monitoring.prometheusRule.enabled=true \
  --set monitoring.grafanaDashboard.enabled=true
```

Prerequisites: a Prometheus reachable from the controller. The `monitoring.*` options need the Prometheus Operator CRDs (`ServiceMonitor`, `PrometheusRule`), and a `GrafanaDashboard` needs grafana-operator. Set `monitoring.*.labels` to whatever your Prometheus selects on (for example `release: prometheus`).

- `agent`: a DaemonSet on every node (tolerates every taint), non-root, read-only root filesystem, no privileges.
- `controller`: runs as root and privileged, because driving GPIO needs `/dev/mem`. It only runs on the nodes you select, and stops at full speed.
- `controllers`: a map of named groups. Each group is a DaemonSet limited by its own `nodeSelector` and merged over `controllerDefaults`, so nodes with different hardware live in one release:

  ```yaml
  controllers:
    pi4:
      nodeSelector: {pifanctl.jyje.online/fan: pi4}
      driver: rpigpio
    pi5:
      nodeSelector: {pifanctl.jyje.online/fan: pi5}
      driver: sysfs
      pwmChannel: 2
  ```

  A group's `nodeSelector` is used exactly as written, never merged with a default. With no groups declared, one `default` group runs on nodes labelled `pifanctl.jyje.online/fan=true`. A node must match at most one group, and a group without a `nodeSelector` is rejected at render time, because it would run everywhere and fight over the pin.
- `monitoring`: an optional `ServiceMonitor`, a `PrometheusRule` (hot node, critical node, agent down, failsafe, fallback, no controller) with a recording rule, and a Grafana dashboard, either as a sidecar `ConfigMap` or as a grafana-operator `GrafanaDashboard`.
- The image tag defaults to `v<appVersion>`, never `latest`. `values.schema.json` rejects unknown drivers and out-of-range duties, and `extraResources` renders any extra manifest with the release.

See [`charts/pifanctl/values.yaml`](charts/pifanctl/values.yaml) for every option and [`charts/pifanctl/ci`](charts/pifanctl/ci) for tested examples.

#### Metrics and alerts

| Metric | From | Meaning |
| --- | --- | --- |
| `pifanctl_temperature_celsius{node,zone,type}` | agent (`:9101`) | One series per thermal zone |
| `pifanctl_node_temperature_max_celsius{node}` | agent | Hottest zone of the node |
| `pifanctl_temperature_read_errors_total{node}` | agent | Reads that found no thermal zone |
| `pifanctl_fan_duty_percent{node}` | controller (`:9102`) | Duty currently applied |
| `pifanctl_control_temperature_celsius{node}` | controller | Temperature the fan acted on |
| `pifanctl_control_followed_node{node,followed}` | controller | The node being followed |
| `pifanctl_control_source{node,source}` | controller | `prometheus`, `local` or `failsafe` |
| `pifanctl_control_fallbacks_total{node,to}` | controller | Cycles that could not use the cluster view |

With `monitoring.prometheusRule.enabled` the chart alerts on: a node above 75 °C for 10 minutes, a node above 82 °C, an agent that is not scraped, a controller on failsafe, a controller that fell back to its own node, and no controller reporting at all.

#### Retention

Temperatures are only as useful as their history. The chart exports metrics but does not own Prometheus, so keep them with the Prometheus settings:

- Set `retention` for the period you want to look back over, and `retentionSize` slightly below the volume size so the TSDB can never fill its disk.
- `pifanctl:node_temperature_max_celsius:max` (recording rule) is one series for the whole cluster. If you downsample or federate to a long-term store, this is the series to send.
- A node count in the single digits costs a few hundred kilobytes per month: the retention budget is decided by the other workloads, not by pifanctl.

### 1.5. OPTION 4: On Kubernetes, raw manifest (one node, no Prometheus)

Run the following command to install the pifanctl on Kubernetes with Raspberry Pies and a PWM Fan.

```sh
kubectl create namespace pifanctl
kubectl apply -n pifanctl -f https://raw.githubusercontent.com/jyje/pifanctl/main/k8s/manifests/deployments.yaml
```

You can check the status of the pifanctl with the following command:

```sh
kubectl get pods -n pifanctl
```

You can check the logs of the pifanctl with the following command:

```sh
kubectl logs -n pifanctl -l app=pifanctl
```



### 1.6. OPTION 5: Run Source Code
```sh
git clone https://github.com/jyje/pifanctl ~/.pifanctl
cd ~/.pifanctl/sources
pip install --upgrade -r requirements.raspi.txt
python ~/.pifanctl/sources/main.py --help
```


### 1.7. Cluster mode: one fan, many nodes

One fan usually cools several boards that sit in the same enclosure. The fan should follow the hottest of them, not the board it happens to be wired to.

| Role | Command | Runs on | What it does |
| --- | --- | --- | --- |
| Agent | `pifanctl agent` | **every node** (DaemonSet) | Reads `/sys/class/thermal` and serves `pifanctl_*` metrics, labelled with `node` |
| Prometheus | | the cluster | Scrapes and **retains** the temperatures |
| Controller | `pifanctl start --source prometheus` | **nodes that have a fan** | Asks Prometheus for `max by (node) (pifanctl_temperature_celsius)` and drives the fan from the hottest node |

The controller never trusts a single source. Each cycle it acts on the highest of the cluster value and its own node's value, and it degrades safely:

1. Prometheus answers: use `max(cluster, local)`.
2. Prometheus is down or empty: use the local temperature, count a fallback.
3. Nothing is readable: run the fan at `--failsafe-duty` (default 100%).

When the controller stops (SIGTERM, pod eviction) the fan is left at `--exit-duty` (default 100%), because a stopped controller no longer protects the board.

With `--source local` (the default) nothing is shared and a node controls only its own fan, exactly like a single board.

```sh
# on every node
pifanctl agent

# on the node with the fan
pifanctl start --source prometheus --prometheus-url http://prometheus:9090
```

#### What the log tells you

Every cycle logs what the fan reacted to and what every node reads, hottest first. The node it followed is marked with `*`:

```
INFO [2026-10-01 14:30:05Z] Duty: 86.3%, Temperature: 70.5°C, Following: node-c, Source: prometheus, Nodes: node-c=70.5* node-b=52.1 node-d=51.8 node-a=49.2
```

A node that reported before and then disappears is warned about once (`Node 'node-c' stopped reporting and is not part of the maximum`), because a silent node may be a hot one. The same facts are metrics: `pifanctl_control_followed_node` (the node being followed) and `pifanctl_control_temperature_celsius`.

#### Temperature curve

`--algorithm curve` (the default) maps temperature to duty. It rises immediately and falls in steps (`--duty-down-step`), which is the hysteresis that keeps the fan from toggling around the threshold.

| Temperature | Duty |
| --- | --- |
| below `--temp-low` (50 °C) | `--duty-idle` (0%) |
| `--temp-low` | `--duty-start` (30%) |
| between | linear ramp |
| `--temp-high` (70 °C) and above | `--duty-max` (100%) |

`--algorithm step` keeps the original behaviour (`--target-temperature`, `--duty-cycle-step`).

#### Drivers

| `--driver` | Use |
| --- | --- |
| `auto` (default) | Kernel PWM on Raspberry Pi 5, RPi.GPIO elsewhere. **Never the mock**: without real hardware the process exits with an error instead of pretending to cool |
| `rpigpio` | Software PWM on `--pin` (Raspberry Pi 4 and older) |
| `sysfs` | Kernel hardware PWM in `/sys/class/pwm` (`--pwm-chip`, `--pwm-channel`); needs the PWM overlay, for example `dtoverlay=pwm-2chan` |
| `mock` | Development only |

Every option is also an environment variable, listed in `pifanctl start --help`.


---
## 2. Build

If you want to build it yourself, you can do the following:

> [!IMPORTANT]
> The package `RPi.GPIO` is available on the Raspberry Pi OS or Linux OS tuned by Raspberry Pi Foundation. So you should run following command on Raspberry Pi.

```sh
git clone https://github.com/jyje/pifanctl ~/.pifanctl
cd ~/.pifanctl/sources
pip install --upgrade -r requirements.raspi.txt
```

Run the tests (they need no Raspberry Pi; the chart tests also need `helm`):

```sh
pip install -r sources/requirements.dev.txt
python -m pytest
```

Then you can debug the source code with the following command:

```sh
python ~/.pifanctl/sources/main.py --help
python ~/.pifanctl/sources/main.py --version
python ~/.pifanctl/sources/main.py status
```


---
## 3. CI/CD Pipeline

This project uses [GitHub Actions with Actions Runner Controller (ARC)](https://github.com/actions/actions-runner-controller) for ARM64-based CI/CD pipeline. The builds are executed on self-hosted Raspberry Pi runners, ensuring native ARM64 compatibility.

You can check the environment of CI/CD pipeline in [app.jyje.online#stack](https://app.jyje.online/#stack)

### 3.1. Workflow Structure

| Workflow | Trigger | What it does |
| --- | --- | --- |
| `ci` | every pull request | Lints the workflows, runs the tests on Python 3.10, 3.11 and 3.14, lints and schema-validates the chart (kubeconform, `promtool`), and builds the ARM64 image on the in-cluster runner without pushing |
| `build-image-main` | push to `main` | Publishes `ghcr.io/jyje/pifanctl:latest`, the commit SHA tag and `v<version>` (once per version) |
| `build-image-develop` | push to `develop` | Publishes `ghcr.io/jyje/pifanctl-dev:latest` and the SHA tag |
| `build-image-issue` | push to `issue-**` | Publishes `ghcr.io/jyje/pifanctl-issue:<sha>` for temporary testing |
| `release-chart` | push to `main` touching `charts/pifanctl` | Publishes the chart to `oci://ghcr.io/jyje/charts/pifanctl` when its version is new |

The three image workflows share one reusable workflow, `_build-image.yaml`.

### 3.2. Key Features

- Native ARM64 builds using self-hosted runners (**`r4spi-microk8s`**, an [ARC](https://github.com/actions/actions-runner-controller) runner scale set in the cluster). Pull requests from forks never run on it
- Skip CI option with **`--no-ci`** in a commit message, evaluated by the workflow engine and never interpolated into a shell script
- GitHub Container Registry (ghcr.io) integration, with immutable `v<version>` tags
- The built image is tested: it prints its version, runs unprivileged, and refuses to start the real GPIO driver where there is no GPIO

### 3.3. Releasing

- Application: bump `__version__` in `sources/pifanctl/__init__.py` and `appVersion` in `charts/pifanctl/Chart.yaml` together (a test checks that they match), then merge to `main`.
- Chart: bump `version` in `charts/pifanctl/Chart.yaml` for any chart change. `release-chart` publishes it.

---
## 4. Trouble Shooting

Is there any problem? see [trouble-shooting.md](docs/trouble-shooting.md)


---
## 5. References

- [Official: Raspberry Pi Foundation](https://www.raspberrypi.org)
- [Blog: Using Raspberry Pi to Control a PWM Fan and Monitor its Speed](https://blog.driftking.tw/en/2019/11/Using-Raspberry-Pi-to-Control-a-PWM-Fan-and-Monitor-its-Speed/)
