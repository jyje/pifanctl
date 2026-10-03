# v1 alpha 런타임 매뉴얼

**구현된 alpha이며, 실물 검증을 마친 정식 버전은 아닙니다.**
`1.0.0-alpha.1`에는 공통 스키마/planner, 센서 freshness metric, worker,
공식 Kubernetes client, operator, CLI와 operator Helm chart가 포함됩니다.
mock 테스트는 실물 PWM을 보증하지 않습니다. 단계별 검증과 출시 게이트는
[PLAN.md](../../PLAN.md)에 기록합니다. [English](runtime.md).

## 01: 물리 냉각 관계를 선택합니다

[시나리오 도해](../../README-ko.md)와 [예시](../../design/v1/examples)를 먼저
실제 배선과 대조합니다. 공유 랙 팬 두 개, 보드별 팬, 한 노드의 여러 팬과 단일
보드를 같은 모델로 관리합니다. `Fan`은 물리 PWM 장치 하나입니다.
`CoolingZone`은 라벨 또는 이름으로 식힐 노드를 선택하고 팬을 연결합니다.
팬을 여러 구역에 연결하면 전체 멤버와 제어 노드의 로컬 온도 중 최고값을 사용합니다.
노드별 Member/Worker CRD를 따로 만들지 않습니다.

```sh
PYTHONPATH=sources python sources/main.py topology validate design/v1/examples/standalone.yaml
PYTHONPATH=sources python sources/main.py topology plan design/v1/examples/standalone.yaml
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

## 02: 로컬 worker를 실행합니다

alpha 소스와 고정 requirements로 설치합니다. 실제 worker는 팬이 배선된 호스트에서
실행합니다. Kubernetes Node 이름이 hostname과 다르면 해당 호스트의 `NODE_NAME`을
설정할 수 있습니다. 다른 호스트에서 원격 하드웨어를 제어하는 옵션이 아닙니다.

```sh
# 실제 배선과 기존 writer를 확인한 팬 호스트에서만 실행합니다.
sudo pifanctl worker run --file topology.yaml --node pi-01
# 가짜 thermal 디렉터리를 사용하는 개발 예시입니다. 하드웨어를 쓰지 않습니다.
pifanctl worker run --file topology.yaml --node pi-01 --mock \
  --thermal-path ./test-thermal --lock-dir ./test-locks --port 9103
```

명시적인 nodeNames는 오프라인에서 사용할 수 있습니다. 선택자는 `--live`와
kubeconfig가 필요하며 파일 변경 시 Node를 다시 해석합니다. operator 모드는
라벨 변경을 계속 반영합니다. 로컬 YAML도 polling으로 전체 파일을 재검증하고
hot reload합니다. 파일은 원자적으로 교체하세요. 잘못된 변경은 이전 정상 plan을
유지하고 팬을 100%로 합니다. 하드웨어 변경은 claim 해제 후 worker 재시작이
필요합니다. 로컬 YAML 모드에는 operator heartbeat가 필요하지 않습니다.

`/var/lock/pifanctl/worker.lock`의 호스트 전체 flock을 CLI와 Pod가 공유합니다.
핀 번호가 달라도 여러 프로세스의 제어는 거부하고, 한 프로세스가 여러 팬을 담당합니다.
새 legacy `start`에도 같은 잠금이 있지만 예전 v0 바이너리에는 없습니다.
이관 전에 반드시 중단해야 합니다. sysfs는 종료 후 커널 PWM을 유지합니다.
RPi.GPIO는 소프트웨어 PWM 스레드를 중단하고 핀을 HIGH로 유지합니다.
이 전기적 상태가 실제 배선에서 full speed인지 반드시 실물 검증해야 합니다.

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
`design/v1/helm`은 토폴로지 CR/ConfigMap을 렌더링하며 런타임을 배포하지 않습니다.

## 04: ConfigMap과 kubectl CLI를 연결합니다

```sh
kubectl --context lab -n pifanctl-system apply -f design/v1/examples/configmap.yaml
helm upgrade --install pifanctl charts/pifanctl-operator -n pifanctl-system \
  --set input.mode=configMap --set input.configMapName=pifanctl-topology
pifanctl --kubeconfig ./lab.config --context lab fan list
pifanctl --context lab zone describe rack-a
pifanctl --context lab fan watch
kubectl pifanctl --context lab fan list
```

입력 ConfigMap과 operator는 같은 namespace에 있어야 합니다. `install.sh`는
동일 CLI로 전달하는 `kubectl-pifanctl`을 설치합니다. fan/zone 명령은 CR 모드를
조회합니다. ConfigMap 모드는 List를 메모리에서 plan으로 변환하고 CR을 생성하지
않습니다. 상태는 같은 namespace의
`pifanctl-status-<sha256(input-name)[:16]>` ConfigMap에 저장합니다.
CR `topology apply`는 server-side apply와 `fieldManager=pifanctl-cli`, `force=false`를
사용합니다. `--dry-run`은 서버에 `dryRun=All`을 전달합니다. 여러 리소스 적용 전체가
하나의 트랜잭션은 아닙니다. Helm/GitOps에서는 원본 저장소를 수정하고 소유권을
강제로 가져오지 않습니다.

## 05: 정상 제어와 장애를 확인합니다

operator는 쓰기 전에 30초 Lease를 갱신합니다. Node/CR watch가 재조정을 깨우고,
5초 전체 resync가 watch 단절과 ConfigMap/workload/report 변경을 복구합니다.
CR과 Node 목록은 별도 API 조회이므로 여러 객체를 동시에 바꾸는 동안 full duty가
일시적으로 발생할 수 있습니다. CR metadata에 설치 소유권을 기록하며 다른 operator는
인수하지 않습니다. 팬 노드마다 worker Deployment 하나가 replicas=1/Recreate로
배치됩니다. 실제 hostname 라벨과 Node 이름 affinity, plan의 Node UID를 확인합니다.
worker에는 Kubernetes 토큰이 없고 leader 상실 시 heartbeat 갱신이 중단됩니다.

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
발행하고 프로세스 내 같은 reason의 빈도를 제한합니다. alpha는 세부 사유를 담은
Ready condition 하나를 구현했습니다. 추가 진단 conditions와 기본 alert rule은
후속 개선입니다. metrics에는 node/fan/zone을 쓰고 hash를 무한한 label로 쌓지 않습니다.
duty는 명령 PWM이며 RPM이 아닙니다. 팬이 물리적으로 멈추거나 전원이 꺼지는 상황의
냉각을 보증하지 않습니다.

## 06: 삭제와 이관을 진행합니다

operator가 실행 중일 때 zone/Fan/입력 ConfigMap을 삭제합니다. 대체 plan의 적용
확인을 기다리고, 구역이 없는 Fan은 100%를 유지합니다. Fan 삭제는 full duty와
드라이버 close를 거쳐 Fan이 없는 plan을 확인합니다. 마지막 Fan이면 Deployment를
삭제하고 Pod가 사라져야 finalizer를 제거합니다. 빈 plan의 확인 기록은 ConfigMap에
남겨 operator 재시작을 견디며 owner GC가 정리합니다. 다른 Fan이 남으면 소유권을
먼저 옮깁니다. worker 연결 불가 시 finalizer는 대기합니다. 강제 제거는 안전 증명이
아니며 별도의 관리자 판단입니다.

배선 조사 → 읽기 전용 plan 대조 → full duty → v0 writer 중단과 프로세스 해제 확인
→ alpha 실행을 팬 호스트별로 진행합니다. 롤백은 alpha 중단과 lock 해제 이후
legacy 복원 순서입니다. 리소스 삭제가 끝나기 전에 operator를 uninstall하지 않습니다.
Node/전원 고장, 실제 Pi 4/Pi 5 PWM, API 서버 CEL/defaulting, fleet 부하는 PLAN.md의
출시 게이트입니다. 이번 구현 작업은 운영 클러스터를 변경하지 않았습니다.
