<div align="center">

# pifanctl: 쿠버네티스 방식의 라즈베리 파이 클러스터 팬 제어

<img alt="쿠버네티스 고래와 공용 PWM 팬이 라즈베리 파이 랙을 함께 식히는 카툰" src="docs/pifanctl-cluster-sticker-concept-1.png" width="560" style="object-fit: contain; max-width: 100%;">

🥧 단일 보드부터 랙까지, 팬을 선언하고 가장 뜨거운 멤버를 따릅니다.

[![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![GitHub ARC](https://img.shields.io/badge/GitHub%20ARC-2088FF?style=flat&logo=GitHub%20Actions&logoColor=white&label=CI)](https://github.com/actions/actions-runner-controller)
[![CLI](https://img.shields.io/badge/CLI-orange?style=flat)](docs/v1/runtime.md)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=Docker&logoColor=white)](https://docker.io)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-326CE5?style=flat&logo=Kubernetes&logoColor=white)](https://kubernetes.io)<br/>
[![CI status for pull requests](https://github.com/jyje/pifanctl/actions/workflows/ci.yaml/badge.svg)](https://github.com/jyje/pifanctl/actions/workflows/ci.yaml)
[![CI status for main branch](https://github.com/jyje/pifanctl/actions/workflows/build-image-main.yaml/badge.svg?branch=main)](https://github.com/jyje/pifanctl/actions/workflows/build-image-main.yaml)
[![CI status for develop branch](https://github.com/jyje/pifanctl/actions/workflows/build-image-develop.yaml/badge.svg?branch=develop)](https://github.com/jyje/pifanctl/actions/workflows/build-image-develop.yaml)
[![Codecov 커버리지](https://codecov.io/gh/jyje/pifanctl/branch/main/graph/badge.svg)](https://app.codecov.io/gh/jyje/pifanctl)
[![GitHub Repo stars](https://img.shields.io/github/stars/jyje/pifanctl?style=flat&color=yellow&label=Stars&cacheSeconds=300)](https://github.com/jyje/pifanctl)

[English](README.md) | **한국어**

</div>

🐳 **pifanctl** (Pi Fan Control)은 Kubernetes에서 라즈베리 파이 냉각 구역의 PWM 팬을 관리합니다. 단일 보드, 공용 팬으로 식히는 4대 랙, 팬이 각각 연결된 여러 랙을 같은 모델로 구성합니다. `Fan`은 팬과 제어 노드이며, `CoolingZone`은 라벨 또는 이름으로 냉각 대상을 선택합니다. 각 팬은 연결된 멤버와 제어 노드의 로컬 센서 중 최고 온도를 따릅니다. operator가 제어 노드마다 worker를 만들고 agent가 Prometheus에 온도를 보고합니다.

**v1:** CRD와 단일 operator 차트가 필수입니다. 독립 `start` 제어는 제거했습니다. 로컬 YAML worker는 `--mock`만 허용하며, 실제 worker는 operator의 계획, Node UID와 heartbeat를 사용합니다. `1.0.0`은 게시되었습니다. `1.1.0` 제안은 기존 values를 유지하면서 Pi 4 RPM 입력을 선택적으로 추가합니다. [RPM 설정과 업그레이드 안내](docs/v1/tachometer.md)를 참고하세요. [지원 범위와 한계](CHANGELOG.md), [릴리즈 계획](PLAN.md)을 참고하세요. 제안된 아티팩트는 게시 후 사용할 수 있습니다.

스티커는 범용 라즈베리 파이 랙, 후면 보드 포트, 전면 공용 팬과 Kubernetes 고래를 표현합니다. [일러스트 스타일과 시안](docs/illustration-style.md).

| 구성 요소 | 역할 |
| --- | --- |
| Fan CR | 물리 팬 하나의 노드, 하드웨어 채널, 온도 곡선, 안전 정책 |
| CoolingZone CR | 식힐 노드와 연결할 팬 |
| Operator | 멤버 선택, 채널 소유권, worker와 상태 조정 |
| Worker | operator 계획과 최신 온도로 해당 노드의 팬 제어 |
| Agent와 Prometheus | 노드별 온도와 센서 시각 발행 및 보관 |

## 1. 설치와 냉각 인스턴스 선언

Kubernetes, ARM64 라즈베리 파이 제어 노드, 접근 가능한 Prometheus와 검증된 배선이 필요합니다. 실물 실험은 Pi 4가 공용 팬을 제어하고 Pi 5가 부하·온도 측정 대상인 혼합 랙에서 진행했습니다. Pi 5 sysfs 팬 제어는 mock 검증만 있으며 실물 검증은 [후속 이슈 #64](https://github.com/jyje/pifanctl/issues/64)로 이관했습니다.

[operator values 예시](tests/fixtures/operator-extra-resources.yaml)를 복사해 실제 하드웨어에 맞추세요. 예시의 `pi-01`과 랙 라벨은 실제 노드로 바꿔야 합니다. 차트 `extraResources` 배열로 인스턴스를 선언합니다. 단일 보드는 멤버 한 대의 CoolingZone과 해당 노드의 Fan으로 구성합니다.

```sh
# 대상 context와 게시된 검토 완료 이미지를 선택합니다.
helm upgrade --install pifanctl charts/pifanctl-operator \
  --kube-context lab --namespace pifanctl-system --create-namespace \
  -f cooling-values.yaml
kubectl --context lab get fans,coolingzones
kubectl --context lab wait --for=condition=Ready fan/rack-fan-01 --timeout=120s
```

1.1.0부터 operator 차트 버전과 `appVersion`은 앱 버전을 따릅니다. 명시적인 `image.tag`는 기본값을 덮어씁니다. 설치 전에 이미지 게시 여부를 확인하세요. Helm은 최초 설치 시 CRD를 설치하지만 스키마 업그레이드는 [런타임 매뉴얼](docs/v1/runtime-ko.md)에 따라 명시적으로 적용해야 합니다. Argo CD에서는 [jyje/cluster](https://github.com/jyje/cluster/blob/main/clusters/r4spi/apps/pifanctl.yaml)처럼 Application에 차트 values와 `extraResources`를 관리합니다.

### CLI와 kubectl

```sh
./install.sh --mock
pifanctl --context lab fan list
kubectl pifanctl --context lab zone describe rack-a
pifanctl topology validate design/v1/examples/two-racks.yaml
pifanctl --context lab topology plan topology.yaml --live
pifanctl --context lab topology apply topology.yaml --dry-run
```

로컬 CLI는 Kubernetes 리소스를 관리합니다. `topology apply`는 소유권을 강제로 덮어쓰지 않는 server-side apply입니다. GitOps 리소스는 원본 저장소에서 수정하세요. `status`는 로컬 온도를 읽고 `agent`는 메트릭을 발행하며 팬을 제어하지 않습니다. 로컬 mock 개발은 런타임 매뉴얼을 확인하세요.

### 냉각과 모니터링

팬은 연결된 모든 구역과 로컬 센서의 최고 온도를 사용합니다. 필요한 온도가 누락되거나 오래되면, 또는 operator heartbeat가 만료되면 안전 duty를 요청합니다. 히스테리시스는 duty 하강을 지연하며 상승은 즉시 적용합니다. duty는 명령값이며 RPM이나 팬 전원 공급을 증명하지 않습니다. [히스테리시스](docs/hysteresis.md), [런타임 메트릭과 자원 해제](docs/v1/runtime-ko.md), [검증 매뉴얼](docs/v1/release-acceptance.md)을 확인하세요.

Prometheus가 각 agent endpoint를 노드별로 수집해야 합니다. Prometheus Operator CRD와 selector가 있을 때만 ServiceMonitor를 활성화하세요. operator 차트는 Prometheus나 기존 controller 대시보드를 설치하지 않습니다. v1 worker를 활성화하기 전에 기존 제어 프로세스를 종료하고 롤백 구성을 보관하세요.

기존 standalone 명령과 차트는 [v0 사용법 보관 문서](docs/legacy/v0-usage-ko.md)에 있습니다.

## 2. 개발과 검증

전체 소프트웨어 검증에는 Python 3.14와 Helm이 필요합니다. 프로젝트 가상 환경에 의존성을 설치하세요.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r sources/requirements.dev.txt
.venv/bin/python -m pytest --cov=sources --cov-branch --cov-report=xml
PYTHONPATH=sources .venv/bin/python sources/main.py --help
```

테스트는 가상 센서와 드라이버를 사용하며 전기적 하드웨어를 인증하지 않습니다. [커버리지와 Codecov](docs/testing/coverage.md)에서 CI와 라인/분기 측정 결과를 설명합니다.

## 3. CI/CD 파이프라인

ARM64 CI/CD에 [GitHub Actions와 Actions Runner Controller (ARC)](https://github.com/actions/actions-runner-controller)를 사용합니다. 빌드는 자체 호스팅 라즈베리 파이 러너에서 실행되어 ARM64 호환성을 네이티브로 보장합니다.

CI/CD 환경은 [app.jyje.online#stack](https://app.jyje.online/#stack)에서 확인할 수 있습니다.

### 3.1. 워크플로 구성

| 워크플로 | 트리거 | 하는 일 |
| --- | --- | --- |
| `ci` | 모든 풀 리퀘스트 | 워크플로 lint, 지원 런타임인 Python 3.14에서 테스트, 차트 lint와 스키마 검증(kubeconform, `promtool`), 클러스터 내 러너에서 ARM64 이미지를 푸시 없이 빌드 |
| `build-image-main` | `main` push | 커밋 SHA 태그와 `v<version>`(버전당 한 번) 발행. 정식 버전만 `latest` 갱신 |
| `build-image-develop` | `develop` push | `ghcr.io/jyje/pifanctl-dev:<commit-sha>`만 발행(7자리 Git SHA). 변경 검증 전 `develop`을 `main` 위로 rebase |
| `build-image-issue` | `issue-**` push | 임시 테스트용 `ghcr.io/jyje/pifanctl-issue:<sha>` 발행 |
| `release-chart` | 두 차트 중 하나를 바꾼 `main` push | 새 `pifanctl`, `pifanctl-operator` 차트를 `oci://ghcr.io/jyje/charts/`에 발행 |

세 이미지 워크플로는 재사용 워크플로 `_build-image.yaml` 하나를 공유합니다.

### 3.2. 주요 기능

- 자체 호스팅 러너(**`r4spi-microk8s`**, 클러스터의 [ARC](https://github.com/actions/actions-runner-controller) 러너 스케일 셋)를 이용한 네이티브 ARM64 빌드. 포크의 풀 리퀘스트는 이 러너에서 실행되지 않습니다
- 커밋 메시지의 **`--no-ci`**로 CI 건너뛰기. 워크플로 엔진이 평가하며 셸 스크립트에 직접 넣지 않습니다
- GitHub Container Registry(ghcr.io) 연동, 불변 `v<version>` 태그
- 빌드된 이미지 테스트: 버전 출력, 권한 없이 실행, GPIO가 없는 곳에서 실제 GPIO 드라이버 기동 거부

### 3.3. 릴리스

1.1.0부터 앱 `__version__`, operator 차트 `version`과 `appVersion`을 같은 버전으로 올립니다. CI가 불일치를 거부합니다. 과거 legacy 차트는 지원되는 게시 범위에서 제외합니다. Changeset에는 `pifanctl`과 `pifanctl-operator`를 함께 기록합니다.

`main`에 병합하면 나머지는 자동입니다.

1. `build-image-main`이 커밋 태그와 버전이 처음 나타날 때 `v<version>`을 발행합니다. 정식 버전만 `latest`를 갱신하고 alpha는 유지합니다.
2. 이미지가 생긴 뒤 git 태그 `v<version>`과 자동 생성 노트가 붙은 GitHub 릴리스를 만듭니다.
3. `release-chart`가 이미지를 기다린 뒤 operator 차트만 `oci://ghcr.io/jyje/charts/pifanctl-operator`에 발행하고 `operator-chart-v<version>` 태그와 릴리스를 만듭니다.

각 단계는 이미 있는 것을 건너뛰므로 실패한 워크플로를 다시 실행해도 안전합니다. 앱 릴리스는 `v*`, 차트는 `chart-v*`와 `operator-chart-v*` 태그를 씁니다. alpha는 GitHub prerelease로 발행합니다.

---
## 4. 런타임과 냉각 시나리오

[런타임 매뉴얼](docs/v1/runtime-ko.md), [오퍼레이터 설계](docs/v1/README-ko.md), [CRD와 예시](design/v1/README.md), [출시 체크리스트](PLAN.md).

#### 냉각 계통 설명: 시나리오 도해

예시 온도로 v1 모델의 동작을 설명합니다. 출력은 정상상태 목표 duty이며 하강 지연은 생략했습니다. 실제 하드웨어 측정값이 아닙니다.

![공유 랙 팬의 정상 동작](docs/v1/figures/rack-normal-ko.png)

<details>
<summary>NORMAL: 보드별 팬</summary>

각 팬은 자기 보드의 온도를 따릅니다.

![보드별 팬: normal](docs/v1/figures/individual-normal-ko.png)

</details>

<details>
<summary>HIGH TEMPERATURE: pi-03 온도 상승</summary>

뜨거워진 멤버에 연결된 팬을 최대 출력으로 올립니다. 다른 냉각 구역에는 영향을 주지 않습니다.

![공유 랙 팬: hot](docs/v1/figures/rack-hot-ko.png)

![보드별 팬: hot](docs/v1/figures/individual-hot-ko.png)

</details>

<details>
<summary>DATA LOST: pi-03 온도 누락</summary>

공유 구역의 온도가 불완전하면 해당 공용 팬을 100%로 합니다. 보드별 팬에서는 누락된 보드의 팬만 안전 동작으로 전환합니다.

![공유 랙 팬: missing](docs/v1/figures/rack-missing-ko.png)

![보드별 팬: missing](docs/v1/figures/individual-missing-ko.png)

</details>

<details>
<summary>WATCHDOG EXPIRED: operator heartbeat 만료</summary>

operator heartbeat가 만료되면 영향을 받은 모든 worker가 팬을 100%로 유지합니다.

![공유 랙 팬: watchdog](docs/v1/figures/rack-watchdog-ko.png)

![보드별 팬: watchdog](docs/v1/figures/individual-watchdog-ko.png)

</details>

[SVG 원본과 렌더링 방법](docs/v1/figures/README.md).

---
## 5. 참고 자료

- [공식: Raspberry Pi Foundation](https://www.raspberrypi.org)
- [블로그: Using Raspberry Pi to Control a PWM Fan and Monitor its Speed](https://blog.driftking.tw/en/2019/11/Using-Raspberry-Pi-to-Control-a-PWM-Fan-and-Monitor-its-Speed/)

### 레거시 CA 런타임 호환성

지원 런타임은 Python 3.14 하나로 고정합니다. 이후 릴리즈는 단일 런타임 이미지를 게시하며, 기존 `-py312` 이미지는 과거 롤백 기록으로 유지됩니다. 호환되지 않는 클러스터 CA 인증서는 배포 전에 바로잡아야 합니다. [CA 유지보수 절차](docs/v1/cluster-ca.md)를 참고하세요.
