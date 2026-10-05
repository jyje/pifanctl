# v1 alpha 런타임 매뉴얼

**구현된 alpha이며, 실물 검증을 마친 정식 버전은 아닙니다.**
`1.0.0-alpha.2`에는 공통 스키마/planner, 센서 freshness metric, worker,
공식 Kubernetes client, operator, CLI와 operator Helm chart가 포함됩니다.
mock 테스트는 실물 PWM을 보증하지 않습니다. 단계별 검증과 출시 게이트는
[PLAN.md](../../PLAN.md)에 기록합니다. [English](runtime.md).

## 01: 물리 냉각 관계를 선택합니다

[시나리오 도해](../../README-ko.md)와 [예시](../../design/v1/examples)를 먼저
실제 배선과 대조합니다. 공유 랙 팬 두 개, 보드별 팬, 한 노드의 여러 팬을
같은 모델로 관리합니다. `Fan`은 물리 PWM 장치 하나입니다.
`CoolingZone`은 라벨 또는 이름으로 식힐 노드를 선택하고 팬을 연결합니다.
팬을 여러 구역에 연결하면 전체 멤버와 제어 노드의 로컬 온도 중 최고값을 사용합니다.
노드별 Member/Worker CRD를 따로 만들지 않습니다.

```sh
PYTHONPATH=sources python sources/main.py topology validate design/v1/examples/two-racks.yaml
PYTHONPATH=sources python sources/main.py topology plan design/v1/examples/two-racks.yaml
# 라벨 선택자는 실제 Node가 필요합니다. API 읽기만 수행합니다.
pifanctl --context lab topology plan design/v1/examples/two-racks.yaml --live
```

`validate`는 필드와 정적인 관계를 검사하고 `plan`은 누락/불건전 관계를 오류 사유로
보존합니다. Node의 Ready=True가 확인되어야 정상 멤버입니다. 리소스를 모두 제거할
때는 `apiVersion: v1`, `kind: List`, `items: []`를 명시합니다. 빈 파일, 중복 키,
NaN과 재귀 alias는 거부합니다. 기존 Fan의 노드/핀/chip/channel은 변경하지 않습니다.
이름을 바꾸며 같은 채널을 재사용하려면 이전 Fan의 해제를 먼저 확인합니다.

선택된 Node가 API에서 삭제되면 이전 기대 멤버에 남겨 full duty를 유지합니다.
멤버의 Node UID가 바뀌어도 `NodeReplaced`로 유지합니다. 이름만 있는 metric으로는
어느 물리 보드인지 증명할 수 없기 때문입니다. 배선을 다시 확인하고 zone을 교체하거나
멤버 선택을 명시적으로 변경해 새 정체성을 확인합니다. 살아 있는 Node의 라벨 변경은
의도적인 멤버 변경으로 반영합니다. 이 보호 정보는 plan에 남아 재시작을 견딥니다.

## 02: operator가 관리하는 worker

v1 operator는 각 `Fan`이 선택한 Node에 worker를 생성하고 관리합니다. 사용자가
독립적인 로컬 PWM controller를 실행하지 않습니다. CRD 상태, worker plan, 실제
하드웨어 제어권을 하나의 Kubernetes 조정 경로에서 관리합니다.
`worker run --mock`은 격리된 소프트웨어 개발에 사용할 수 있지만, 로컬 실물 팬
제어는 v1 제품 범위에 포함되지 않습니다.

## 03: Kubernetes를 준비합니다

**PR을 작성했다고 alpha 이미지가 registry에 생기는 것은 아닙니다.** 검토 후 main
빌드가 게시하거나, 이 코드를 포함한 테스트 이미지 태그를 직접 지정해야 합니다.
정식 v1.0.0은 별도의 하드웨어 출시 게이트를 통과한 뒤 진행합니다.

```sh
helm lint charts/pifanctl-operator
helm template pifanctl charts/pifanctl-operator -n pifanctl-system
# 이미지를 준비하고 명시적으로 선택한 검토 클러스터에서만 적용합니다.
helm upgrade --install pifanctl charts/pifanctl-operator \
  -n pifanctl-system --create-namespace
pifanctl --context lab topology apply topology.yaml --dry-run
pifanctl --context lab topology apply topology.yaml
kubectl --context lab get fans,coolingzones
kubectl --context lab wait --for=condition=Ready fan/fan-01
```

chart는 agent를 관리하거나 기존 agent를 재사용합니다. 재사용 agent에도
`pifanctl_temperature_observed_timestamp_seconds`가 있어야 합니다. Prometheus는
각 agent endpoint를 모두 scrape하고 `node` 라벨을 보존해야 합니다. Service 주소의
backend 한 개만 읽으면 전체 노드 데이터가 아닙니다. Prometheus Operator가 설치되어
있고 selector가 맞으면 ServiceMonitor를 켭니다. 그 외에는 Pod/Endpoint별 scrape를
직접 구성합니다. read-time metric이 없는 예전 agent는 원격 구역을 불건전하게 만들고
팬은 full duty를 요청합니다.

Helm은 CRD를 최초 설치하지만 갱신하지 않습니다. 스키마 변경은
`charts/pifanctl-operator/crds/`를 검토하고 명시적으로 적용합니다.
`charts/pifanctl-operator`는 런타임을 설치하고 `extraResources`로 인스턴스 CR을
렌더링합니다. GitOps Application의 Helm 값으로 배열을 관리합니다. 설계용 차트는
지원되는 v1 설치 경로가 아닙니다.

## 04: CR 인스턴스와 kubectl CLI를 연결합니다

```sh
pifanctl --kubeconfig ./lab.config --context lab fan list
pifanctl --context lab zone describe rack-a
pifanctl --context lab fan watch
kubectl pifanctl --context lab fan list
```

operator 차트의 `extraResources` 값에 cluster `Fan`과 `CoolingZone` 객체를
선언합니다. 차트가 CRD를 설치하고 인스턴스 리소스를 적용합니다. Argo CD에서는
operator Application의 Helm 값에 배열을 두고 GitOps가 변경을 소유하게 합니다.
`install.sh`는 같은 kubeconfig 기반 조회 CLI를 사용하는 `kubectl-pifanctl`을
설치합니다. CLI `topology apply`는 `fieldManager=pifanctl-cli`, `force=false`로
server-side apply를 사용하고 `--dry-run`은 `dryRun=All`을 보냅니다. 여러 리소스의
적용은 하나의 트랜잭션이 아닙니다. Helm/GitOps에서는 원본 저장소를 수정합니다.

### 곡선과 온도 히스테리시스

Fan의 `spec.control.curve`는 가장 뜨거운 담당 온도를 duty로 바꿉니다. 필드는
`temperatureLow`, `temperatureHigh`, `dutyIdle`, `dutyStart`, `dutyMax`,
`dutyDownStep`, `temperatureHysteresis`입니다.

`temperatureHysteresis`(기본 `5`, 섭씨)는 온도가 최고점보다 얼마나 내려와야 duty가
따라 내려가는지를 정합니다. 팬은 `temperatureLow`에서 켜지지만 온도가 그 최고점보다
`temperatureHysteresis` 아래로 내려와야 멈추므로, 시작점 아래로 자기 구역을 식히는
팬이 반복해서 켜졌다 꺼지지 않습니다. 올라가는 온도는 지연하지 않습니다. `0`이면
꺼지고, `temperatureHigh - temperatureLow`보다 작아야 하며 CRD와 planner가 모두
검증합니다. `dutyDownStep`은 별개이며, 내려갈 수 있게 된 뒤 얼마나 빠르게 내려가는지를
제한합니다.

그래프, 계산 예시, 값 고르는 법은 [온도 히스테리시스](../hysteresis-ko.md)를 보세요.

## 05: 정상 제어와 장애를 확인합니다

operator는 쓰기 전에 30초 Lease를 갱신합니다. Node/CR watch가 재조정을 깨우고,
5초 전체 resync가 watch 단절과 ConfigMap/workload/report 변경을 복구합니다.
CR과 Node 목록은 별도 API 조회이므로 여러 객체를 동시에 바꾸는 동안 full duty가
일시적으로 발생할 수 있습니다. CR metadata에 설치 소유권을 기록하며 다른 operator는
인수하지 않습니다. 팬 노드마다 worker Deployment 하나가 replicas=1/Recreate로
배치됩니다. 실제 hostname 라벨과 Node 이름 affinity, plan의 Node UID를 확인합니다.
worker에는 Kubernetes 토큰이 없고 leader 상실 시 heartbeat 갱신이 중단됩니다.

CR 소유권은 `namespace/operatorId`로 기록합니다. 다른 namespace에서 같은 ID를
사용해도 인수할 수 없습니다. alpha의 cluster-wide CR 토폴로지는 설치 한 개가
담당하고, 그 설치의 replicas가 Lease를 공유합니다. alpha 차트는 operator 하나를
기본값으로 사용하고 리더만 Ready인 구조의 교체 대기를 방지하려고 Recreate로
교체합니다. 교체 중에도 worker heartbeat 만료 보호가 동작합니다. 여러 replica의
readiness와 업그레이드 가용성은 후속 개선입니다.

ConfigMap 디렉터리 전달에는 지연이 있습니다. worker는 plan과 별도의 heartbeat를
읽고 hash/UID를 비교합니다. 미래 시각은 최대 5초 허용합니다.
**watchdog 기본값은 120초**입니다. 실제 projection 지연을 측정해야 하며, 전달이
늦으면 full duty가 발생할 수 있습니다. heartbeat가 정상이어도 온도 누락/stale 검사는
우회하지 않습니다. duty 하강은 팬별 refresh interval을 지키고, 상승과 장애는 읽은
즉시 반영합니다.

별도 worker 스레드가 1초마다 heartbeat 만료와 제어 루프 진행을 감시합니다.
Prometheus 조회와 독립적으로 full duty를 요청하고, 뒤늦은 조회 결과는 안전
latch를 해제하지 못합니다. main loop가 재검증한 뒤에만 정상 제어를 재개합니다.

| 관측 | 의미 |
| --- | --- |
| worker :9103 `/status`, `/metrics` | 적용 hash, 명령 duty, 멤버 온도와 실패 사유 |
| `/healthz` | HTTP 프로세스 생존, 실제 냉각 확인은 아님 |
| `/readyz` | 모든 팬의 제어 입력이 정상, 불건전하면 503 |
| Fan/CoolingZone Ready | 신선한 worker report의 hash/UID와 정상 입력 확인 |
| operator :9104 | health/ready/metrics, Lease leader만 Ready |

worker report는 최대 90초까지 유효합니다. 안정 상태의 status 쓰기는 객체당
30초에 한 번이며 readiness/reason/config 변경은 즉시 반영합니다. Event는 전환 시
발행하고 프로세스 내 같은 reason의 빈도를 제한합니다. cluster scoped CR의
Event는 `default`에 저장하며 차트는 해당 namespace에 Event 생성 권한만 부여합니다.
Event API 실패는 로그와 재시도로 처리하고 heartbeat 갱신을 막지 않습니다. alpha는 세부 사유를 담은
Ready condition 하나를 구현했습니다. 추가 진단 conditions와 기본 alert rule은
후속 개선입니다. metrics에는 node/fan/zone을 쓰고 hash를 무한한 label로 쌓지 않습니다.
duty는 명령 PWM이며 RPM이 아닙니다. 팬이 물리적으로 멈추거나 전원이 꺼지는 상황의
냉각을 보증하지 않습니다.

### 안전 상태를 수집합니다

`serviceMonitor.enabled`와 Prometheus selector label, monitoring namespace의
NetworkPolicy를 설정합니다. worker Service는 unready endpoint도 공개하므로
failsafe 중에도 `pifanctl_worker_fan_ready == 0` 지표를 수집할 수 있습니다.
agent 재사용과 관리형 agent 모두 worker ServiceMonitor를 제공합니다. 기존
controller 경보와 dashboard는 worker duty/readiness 지표로 명시적으로 이관하고,
온도 경보와 scrape 실패 감시를 유지합니다. absent-series 경보는 설치나 팬 목록으로
범위를 제한합니다.

## 06: 삭제와 이관을 진행합니다

operator가 실행 중일 때 zone/Fan을 삭제합니다.
`kubectl delete ... --cascade=background` 기본값을 사용합니다. foreground GC는
release 확인 전에 worker를 삭제하여 앱 finalizer가 대기할 수 있으므로 alpha의
지원 삭제 경로가 아닙니다. 대체 plan의 적용 확인을 기다리고, 구역이 없는 Fan은
100%를 유지합니다. Fan 삭제는 full duty와
드라이버 close를 거쳐 Fan이 없는 plan을 확인합니다. 마지막 Fan이면 Deployment를
삭제하고 Pod가 사라져야 finalizer를 제거합니다. 빈 plan의 확인 기록은 ConfigMap에
남겨 operator 재시작을 견디며 owner GC가 정리합니다. 다른 Fan이 남으면 소유권을
먼저 옮깁니다. worker 연결 불가 시 finalizer는 대기합니다. 강제 제거는 안전 증명이
아니며 별도의 관리자 판단입니다.

배선 조사 → 읽기 전용 plan 대조 → full duty → v0 writer 중단과 프로세스 해제 확인
→ alpha 실행을 팬 호스트별로 진행합니다. 롤백은 alpha 중단과 lock 해제 이후
legacy 복원 순서입니다. 리소스 삭제가 끝나기 전에 operator를 uninstall하지 않습니다.
Node/전원 고장, 실제 Pi 4/Pi 5 PWM, API 서버 CEL/defaulting, fleet 부하는 PLAN.md의
출시 게이트입니다. 실제 배포는 명시적으로 승인된 실험과 보관된 롤백 계획이 필요합니다.

## 오래된 클러스터 CA와 런타임 호환성

Python 3.13 이후의 엄격한 X.509 검증은 필수 extension이 없는 예전 CA를 거부할
수 있습니다. 인증서와 호스트명 검증은 켜둡니다. CA 갱신을 별도 계획하면서 지원
대상인 Python 3.12 런타임으로 실험용 이미지를 만들 수 있습니다.

```sh
gh workflow run build-image-issue.yaml --ref YOUR_BRANCH -f python-version=3.12
```

이미지는 `ghcr.io/jyje/pifanctl-issue:<sha>-py312`이며 latest나 릴리스 태그를
발행할 수 없습니다. operator chart의 image repository/tag를 이 이미지로 지정하고,
operator Ready를 확인한 뒤 물리 Fan을 할당합니다. 기본 이미지는 Python 3.14이고,
CI는 계속 Python 3.10-3.14 전체를 검사합니다.
[Python SSL 문서](https://docs.python.org/3/library/ssl.html#ssl.create_default_context)를 참고합니다.
