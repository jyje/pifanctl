<div align="center">

# pifanctl: 라즈베리 파이 팬 컨트롤러

[English](README.md) | **한국어**

<img alt="pifanctl logo" src="docs/whale-cooling-pie.jpg" width="450" style="object-fit: contain; max-width: 100%; aspect-ratio: 16 / 9;">

🥧 **라즈베리 파이**의 **PWM 팬 제어** CLI

[![Python Typer](https://img.shields.io/badge/Typer-3776AB?style=flat&logo=Python&logoColor=white&label=Python)](https://typer.tiangolo.com/)
[![GitHub ARC](https://img.shields.io/badge/GitHub%20ARC-2088FF?style=flat&logo=GitHub%20Actions&logoColor=white&label=CI)](https://github.com/actions/actions-runner-controller)
[![CLI](https://img.shields.io/badge/CLI-orange?style=flat&logo=Typer&logoColor=white)](https://typer.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=Docker&logoColor=white)](https://docker.io)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-326CE5?style=flat&logo=Kubernetes&logoColor=white)](https://kubernetes.io)<br/>
[![CI status for main branch](https://github.com/jyje/pifanctl/actions/workflows/build-image-main.yaml/badge.svg?branch=main)](https://github.com/jyje/pifanctl/actions/workflows/build-image-main.yaml)
[![CI status for develop branch](https://github.com/jyje/pifanctl/actions/workflows/build-image-develop.yaml/badge.svg?branch=develop)](https://github.com/jyje/pifanctl/actions/workflows/build-image-develop.yaml)
[![GitHub Repo stars](https://img.shields.io/github/stars/jyje/pifanctl?style=flat&color=yellow&label=%F0%9F%8C%9F%20Stars)](https://github.com/jyje/pifanctl)


</div>

🐳 **pifanctl**은 라즈베리 파이의 PWM 팬을 제어하는 CLI입니다. 보드 한 대부터 클러스터 전체까지 지원하며, 일반 CLI, **Docker**, 또는 Helm 차트를 이용한 **Kubernetes**로 실행할 수 있고 ARM64에 최적화되어 있습니다. 클러스터에서는 팬이 **가장 뜨거운 노드**를 기준으로 동작하고, 모든 노드의 온도가 Prometheus에 보관됩니다. GitHub Actions와 Actions Runner Controller(ARC)로 구성한 CI/CD를 사용하므로 모든 빌드가 실제 라즈베리 파이에서 테스트됩니다.

---
## 1. 실행

### 1.1. 요구 사항

- Raspberry Pi (ARM64)
- Python 3.10+

아래 명령은 Raspberry Pi (ARM64)에 접속해서 실행하세요.

### 1.2. 옵션 1: 패키지처럼 CLI 설치

```sh
curl -fsSL https://raw.githubusercontent.com/jyje/pifanctl/main/install.sh -o install-pifanctl.sh
chmod +x install-pifanctl.sh
./install-pifanctl.sh
rm install-pifanctl.sh

## 삭제
# rm -rf $HOME/.pifanctl
```

설치 후 `pifanctl --help`로 사용법을 확인하세요.

### 1.3. 옵션 2: Docker

```sh
docker run -it ghcr.io/jyje/pifanctl python main.py --help
```

팬을 구동하려면:

```sh
docker run --privileged -it ghcr.io/jyje/pifanctl python main.py start
```

핀 제어에는 GPIO 접근이 필요해서 `start`에는 `docker run --privileged`가 필요합니다. `agent`와 `status`는 권한 없이 실행되고, 이미지는 기본적으로 non-root 사용자로 실행됩니다.

### 1.4. 옵션 3: Helm으로 Kubernetes에 설치 (권장)

```sh
kubectl label node <팬이-달린-노드> pifanctl.jyje.online/fan=true

helm install pifanctl oci://ghcr.io/jyje/charts/pifanctl \
  --namespace pifanctl --create-namespace \
  --set prometheus.url=http://prometheus-operated.monitoring.svc:9090 \
  --set monitoring.serviceMonitor.enabled=true \
  --set monitoring.prometheusRule.enabled=true \
  --set monitoring.grafanaDashboard.enabled=true
```

- `agent`: 모든 노드에서 도는 DaemonSet (모든 taint 허용), non-root, 읽기 전용 루트 파일시스템, 권한 없음.
- `controllers`: 이름 있는 그룹의 맵입니다. 각 그룹은 자신의 `nodeSelector`로 한정된 DaemonSet이고 `controllerDefaults` 위에 덮어써지므로, 하드웨어가 다른 노드를 한 릴리스에 함께 선언할 수 있습니다.

  ```yaml
  controllers:
    default: null          # 차트 기본 그룹 제거
    pi4:
      nodeSelector: {pifanctl.jyje.online/fan: pi4}
      driver: rpigpio
    pi5:
      nodeSelector: {pifanctl.jyje.online/fan: pi5}
      driver: sysfs
      pwmChannel: 2
  ```

  노드는 최대 한 그룹에만 일치해야 합니다. `nodeSelector`가 없는 그룹은 모든 노드에서 실행되어 핀을 두고 다툴 수 있으므로 렌더링 단계에서 거부됩니다.
- `monitoring`: 선택 사항인 `ServiceMonitor`, `PrometheusRule`(뜨거운 노드, 위험 온도, agent 중단, failsafe, 폴백, 컨트롤러 없음)과 recording rule, 그리고 Grafana 대시보드(사이드카용 `ConfigMap` 또는 grafana-operator `GrafanaDashboard`).
- 이미지 태그는 기본값이 `v<appVersion>`이며 `latest`는 쓰지 않습니다. `values.schema.json`이 알 수 없는 드라이버나 범위를 벗어난 duty를 거부하고, `extraResources`로 추가 매니페스트를 릴리스와 함께 렌더링할 수 있습니다.

모든 옵션은 [`charts/pifanctl/values.yaml`](charts/pifanctl/values.yaml), 검증된 예시는 [`charts/pifanctl/ci`](charts/pifanctl/ci)를 보세요.

#### 보관(Retention)

온도는 이력이 있어야 쓸모가 있습니다. 이 차트는 메트릭을 내보낼 뿐 Prometheus를 소유하지 않으므로, 보관 설정은 Prometheus 쪽에서 합니다.

- 돌아보고 싶은 기간만큼 `retention`을 설정하고, TSDB가 디스크를 가득 채우지 않도록 `retentionSize`를 볼륨 크기보다 조금 작게 지정하세요.
- recording rule `pifanctl:node_temperature_max_celsius:max`는 클러스터 전체를 나타내는 시계열 하나입니다. 다운샘플링이나 장기 저장소로 보낼 때는 이 시계열을 보내면 됩니다.
- 노드가 한 자릿수라면 한 달에 수백 KB 수준입니다. 보관 용량은 pifanctl이 아니라 다른 워크로드가 좌우합니다.

### 1.5. 옵션 4: 원시 매니페스트로 Kubernetes에 설치 (노드 1대, Prometheus 없음)

```sh
kubectl create namespace pifanctl
kubectl apply -n pifanctl -f https://raw.githubusercontent.com/jyje/pifanctl/main/k8s/manifests/deployments.yaml
```

```sh
kubectl get pods -n pifanctl
kubectl logs -n pifanctl -l app=pifanctl
```

### 1.6. 옵션 5: 소스 코드 직접 실행

```sh
git clone https://github.com/jyje/pifanctl ~/.pifanctl
cd ~/.pifanctl/sources
pip install --upgrade -r requirements.raspi.txt
python ~/.pifanctl/sources/main.py --help
```

### 1.7. 클러스터 모드: 팬 하나, 노드 여러 개

팬 하나가 같은 케이스 안의 여러 보드를 식히는 경우가 많습니다. 팬은 자신이 연결된 보드가 아니라 **그중 가장 뜨거운 보드**를 따라야 합니다.

| 역할 | 명령 | 실행 위치 | 하는 일 |
| --- | --- | --- | --- |
| Agent | `pifanctl agent` | **모든 노드** (DaemonSet) | `/sys/class/thermal`을 읽어 `node` 라벨이 붙은 `pifanctl_*` 메트릭을 노출 |
| Prometheus | | 클러스터 | 온도를 수집하고 **보관** |
| Controller | `pifanctl start --source prometheus` | **팬이 달린 노드** | Prometheus에 `max(pifanctl_temperature_celsius)`를 질의해 그 값으로 팬 구동 |

컨트롤러는 한 가지 소스만 믿지 않습니다. 매 주기마다 클러스터 값과 자기 노드 값 중 **높은 쪽**으로 동작하고, 안전하게 단계적으로 물러납니다.

1. Prometheus가 응답: `max(cluster, local)` 사용.
2. Prometheus가 중단되었거나 비어 있음: 로컬 온도를 사용하고 폴백을 기록.
3. 아무것도 읽을 수 없음: `--failsafe-duty`(기본 100%)로 팬 구동.

컨트롤러가 멈추면(SIGTERM, Pod 축출) 팬은 `--exit-duty`(기본 100%)로 남습니다. 멈춘 컨트롤러는 더 이상 보드를 지켜주지 못하기 때문입니다.

`--source local`(기본값)에서는 아무것도 공유하지 않으며, 보드 한 대일 때처럼 노드가 자기 팬만 제어합니다.

```sh
# 모든 노드에서
pifanctl agent

# 팬이 달린 노드에서
pifanctl start --source prometheus --prometheus-url http://prometheus:9090
```

#### 온도 곡선

`--algorithm curve`(기본값)는 온도를 duty로 변환합니다. 올라갈 때는 즉시, 내려갈 때는 단계적으로(`--duty-down-step`) 움직이며, 이것이 임계값 근처에서 팬이 켜졌다 꺼졌다 하는 것을 막는 히스테리시스입니다.

| 온도 | Duty |
| --- | --- |
| `--temp-low`(50 °C) 미만 | `--duty-idle`(0%) |
| `--temp-low` | `--duty-start`(30%) |
| 그 사이 | 선형 증가 |
| `--temp-high`(70 °C) 이상 | `--duty-max`(100%) |

`--algorithm step`은 기존 동작(`--target-temperature`, `--duty-cycle-step`)을 유지합니다.

#### 드라이버

| `--driver` | 용도 |
| --- | --- |
| `auto`(기본값) | 라즈베리 파이 5는 커널 PWM, 그 외는 RPi.GPIO. **mock은 절대 선택하지 않으며**, 실제 하드웨어가 없으면 냉각하는 척하지 않고 오류로 종료 |
| `rpigpio` | `--pin`에 소프트웨어 PWM (라즈베리 파이 4 이하) |
| `sysfs` | `/sys/class/pwm`의 커널 하드웨어 PWM (`--pwm-chip`, `--pwm-channel`). PWM 오버레이 필요, 예: `dtoverlay=pwm-2chan` |
| `mock` | 개발 전용 |

모든 옵션은 환경 변수로도 지정할 수 있으며 `pifanctl start --help`에 나와 있습니다.

---
## 2. 빌드

> [!IMPORTANT]
> `RPi.GPIO` 패키지는 라즈베리 파이 OS(또는 라즈베리 파이 재단이 튜닝한 Linux)에서만 사용할 수 있습니다. 이 명령은 라즈베리 파이에서 실행하세요.

```sh
git clone https://github.com/jyje/pifanctl ~/.pifanctl
cd ~/.pifanctl/sources
pip install --upgrade -r requirements.raspi.txt
```

테스트는 라즈베리 파이가 필요 없습니다(차트 테스트는 `helm`도 필요).

```sh
pip install -r sources/requirements.dev.txt
python -m pytest
```

```sh
python ~/.pifanctl/sources/main.py --help
python ~/.pifanctl/sources/main.py --version
python ~/.pifanctl/sources/main.py status
```

---
## 3. CI/CD 파이프라인

ARM64 CI/CD에 [GitHub Actions와 Actions Runner Controller (ARC)](https://github.com/actions/actions-runner-controller)를 사용합니다. 빌드는 자체 호스팅 라즈베리 파이 러너에서 실행되어 ARM64 호환성을 네이티브로 보장합니다.

### 3.1. 워크플로 구성

| 워크플로 | 트리거 | 하는 일 |
| --- | --- | --- |
| `ci` | 모든 풀 리퀘스트 | 워크플로 lint, Python 3.10/3.11/3.14 테스트, 차트 lint와 스키마 검증(kubeconform, `promtool`), 클러스터 내 러너에서 ARM64 이미지를 푸시 없이 빌드 |
| `build-image-main` | `main` push | `ghcr.io/jyje/pifanctl:latest`, 커밋 SHA 태그, `v<version>`(버전당 한 번) 발행 |
| `build-image-develop` | `develop` push | `ghcr.io/jyje/pifanctl-dev:latest`와 SHA 태그 발행 |
| `build-image-issue` | `issue-**` push | 임시 테스트용 `ghcr.io/jyje/pifanctl-issue:<sha>` 발행 |
| `release-chart` | `charts/pifanctl`을 바꾼 `main` push | 버전이 새로울 때 `oci://ghcr.io/jyje/charts/pifanctl`에 차트 발행 |

세 이미지 워크플로는 재사용 워크플로 `_build-image.yaml` 하나를 공유합니다.

### 3.2. 주요 기능

- 자체 호스팅 러너(**`r4spi-microk8s`**, 클러스터의 [ARC](https://github.com/actions/actions-runner-controller) 러너 스케일 셋)를 이용한 네이티브 ARM64 빌드. 포크의 풀 리퀘스트는 이 러너에서 실행되지 않습니다
- 커밋 메시지의 **`--no-ci`**로 CI 건너뛰기. 워크플로 엔진이 평가하며 셸 스크립트에 직접 넣지 않습니다
- GitHub Container Registry(ghcr.io) 연동, 불변 `v<version>` 태그
- 빌드된 이미지 테스트: 버전 출력, 권한 없이 실행, GPIO가 없는 곳에서 실제 GPIO 드라이버 기동 거부

### 3.3. 릴리스

- 애플리케이션: `sources/pifanctl/__init__.py`의 `__version__`과 `charts/pifanctl/Chart.yaml`의 `appVersion`을 함께 올리고(일치 여부를 테스트가 확인) `main`에 병합합니다.
- 차트: 차트가 바뀌면 `charts/pifanctl/Chart.yaml`의 `version`을 올립니다. `release-chart`가 발행합니다.

---
## 4. 문제 해결

문제가 있나요? [trouble-shooting.md](docs/trouble-shooting.md)를 보세요.

---
## 5. 참고 자료

- [공식: Raspberry Pi Foundation](https://www.raspberrypi.org)
- [블로그: Using Raspberry Pi to Control a PWM Fan and Monitor its Speed](https://blog.driftking.tw/en/2019/11/Using-Raspberry-Pi-to-Control-a-PWM-Fan-and-Monitor-its-Speed/)
