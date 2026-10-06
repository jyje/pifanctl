# v1: 냉각 토폴로지와 오퍼레이터 설계

[English](README.md) | **한국어**

**구현된 alpha (`1.0.0-alpha.3`)이며 정식 v1 출시는 아닙니다.**
공통 planner, freshness metric, worker, operator, CLI와 차트를 구현했습니다.
현재 명령과 제한은 [런타임 매뉴얼](runtime-ko.md), 검증과 하드웨어 출시 게이트는
[PLAN.md](../../PLAN.md)를 확인하세요. 후보는 `v1`과 `v1alpha1` 호환 API를 제공합니다. [API 전환 절차](api-migration.md)를 확인하세요.

후속 구현 로드맵: [이슈 #39](https://github.com/jyje/pifanctl/issues/39).

## 1. 현재 구조와 개선 범위

현재 agent는 각 노드의 온도를 Prometheus로 내보내고, 팬이 연결된 노드의
controller가 Prometheus 쿼리와 자신의 온도를 기준으로 PWM을 제어합니다.
Helm에서 controller 그룹마다 노드 선택, 하드웨어, Prometheus 쿼리를 다르게
설정할 수 있습니다. 기본 쿼리는 전체 클러스터를 포함합니다.

수동 쿼리로 온도 대상을 좁힐 수 있지만, 어떤 노드를 어떤 팬이 식히는지 명시적인
모델이 없습니다. 원격 샘플이 없어지면 최대값에서 제외하고, 원격 쿼리가 실패하면
로컬 온도로 대체합니다. 공유 팬이 식히는 다른 보드의 상태를 보장하는 방식은
아니므로 v1에서는 멤버십과 데이터 완전성을 함께 관리합니다.

## 2. 재설계 판단: 라벨과 리소스를 함께 사용

`FanMember`와 `FanWorker`는 역할을 설명하는 좋은 출발점입니다. 다만 노드마다
별도의 객체를 만들면 기존 `Node`와 정체성이 중복됩니다. 노드는 냉각 대상이면서
팬 제어 노드일 수 있고, 팬 여러 개가 한 노드에 연결될 수도 있습니다.

| 방식 | 장점 | 한계 | 채택 범위 |
| --- | --- | --- | --- |
| Node 라벨만 사용 | Kubernetes 기본 기능, 간편한 그룹화 | PWM 설정, 여러 팬, 제어 곡선, 참조와 상태를 라벨로 관리하기 부적절 | 냉각 대상 선택 |
| 노드별 Member/Worker CRD | 역할을 개별적으로 표현 | Node 중복, 팬 여러 개의 정체성 불명확, 노드 수만큼 객체 증가 | 채택하지 않음 |
| 전체 토폴로지 ConfigMap | YAML·Helm·GitOps로 연결하기 쉬움 | 문서 전체 갱신과 별도 상태 관리 필요 | v1 제외, CRD 필수 |
| CoolingZone + Fan CRD | 대상 중심 구성, 물리 팬 구분, 구조화된 설정과 상태 | 오퍼레이터와 참조 검증 필요 | 권장 Kubernetes API |

결론은 **냉각 대상은 Node 라벨이나 이름으로 선택하고, 냉각 구역과 물리 팬은
별도 리소스로 관리**하는 혼합 구성입니다. 초기에는 `FanGroup`, `CoolingPolicy`
같은 추가 CRD를 만들지 않습니다.
[Kubernetes 라벨과 선택자](https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/),
[사용자 정의 리소스](https://kubernetes.io/docs/concepts/extend-kubernetes/api-extension/custom-resources/).

## 3. API 구성

Node와 물리 PWM 장치의 범위에 맞춰 두 리소스 모두 cluster scope입니다.
처음에는 클러스터 관리자가 관리합니다. 여러 tenant에게 하드웨어 제어 권한을
위임하려면 별도의 권한 모델이 필요합니다.

### Fan: 물리 팬 하나

- `spec.nodeName`: 팬이 실제 연결된 Node 이름 하나. 여러 노드를 선택하는
  selector를 사용하지 않습니다. 생성 이후 변경할 수 없습니다.
- `spec.hardware`: `rpigpio` 또는 `sysfs` 중 하나를 명시합니다. 하드웨어 설정은
  불변입니다. 운영 리소스에서 자동 감지나 mock 드라이버는 사용하지 않습니다.
- `spec.control`: 온도별 duty 곡선과 제어 주기. alpha에서는 failsafe와 종료 duty를
  100%로 고정합니다.
- 상태: 물리 장치 claim, Node UID, worker Pod, 구역 목록, 설정 hash와 적용 hash,
  heartbeat, 제어 온도와 요청 duty, conditions.

한 노드에 서로 다른 PWM 핀/채널의 Fan 여러 개를 둘 수 있습니다. claim은 GPIO의
경우 `(Node UID, BCM pin)`, sysfs의 경우 `(Node UID, chip, channel)`입니다.
물리 핀 별칭을 확실히 알아낼 수 없으므로 alpha에서는 같은 노드에서 GPIO와
sysfs를 혼용하는 구성을 거부합니다. 이동/교체는 기존 claim 해제를 확인한 뒤
진행합니다.

### CoolingZone: 냉각 대상부터 정의하는 구역

- `spec.nodeSelector`: Kubernetes LabelSelector, 또는 `spec.nodeNames`: 명시한
  Node 이름 목록. 둘 중 하나만 사용하며 빈 선택자는 거부합니다.
- `spec.fanRefs`: 해당 구역을 식히는 Fan 이름 목록. Fan의 구역 목록은 이 참조에서
  계산합니다. 양쪽에 같은 관계를 중복 선언하지 않습니다.
- `spec.telemetry`: Prometheus URL과 샘플 허용 나이, 또는 단일 노드용 `local`.
  local은 이름으로 명시한 노드 한 대와 그 노드에 연결된 팬에만 허용합니다.
- 상태: 실제 선택된 노드, 온도가 없는 노드, 연결된 팬, 최고 온도와 관측 시간,
  설정 hash와 conditions.

노드와 구역, 구역과 팬은 다대다입니다. 팬 하나가 여러 구역을 식힐 때는 모든
연결 구역의 노드 합집합에서 최고 온도를 사용합니다. 팬 제어 노드의 현재 온도는
추가적인 안전 하한입니다. 물리 팬 하나에 서로 다른 제어 곡선을 적용하지 않습니다.
한 팬의 입력에서 같은 노드에 서로 다른 telemetry 정의가 충돌하면 거부합니다.
Prometheus의 `node` 값은 Kubernetes Node 이름과 정확히 같아야 합니다.

개별 필드, 범위, 불변성, 선택 방식은 CRD 스키마/CEL로 검증하고, 참조 대상 존재,
물리 장치 충돌, local 배치와 데이터 완전성은 공통 validator/planner와 worker가
검증합니다. Helm JSON Schema는 CEL을 실행하지 않으므로 같은 의미 검증을
planner에서도 수행합니다. Node 라벨 key/value의 문법도 검증합니다.
[CRD 스키마와 status subresource](https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definitions/).

## 4. 지원할 물리 구성

| 구성 | 모델 |
| --- | --- |
| 팬 두 개, 각각 네 대 냉각 | rack-a 네 대 → fan-01, rack-b 네 대 → fan-02 |
| 각 Pi에 PWM 팬 하나 | 노드 한 대짜리 CoolingZone과 같은 노드의 Fan |
| 네 대를 팬 두 개로 냉각 | CoolingZone 하나에서 Fan 두 개 참조 |
| 한 노드에서 팬 여러 개 제어 | 같은 nodeName, 서로 다른 핀/채널의 Fan |
| 팬 하나가 여러 구역 냉각 | 여러 CoolingZone에서 같은 Fan 참조, 대상 합집합의 최고 온도 |
| 단일 노드 Kubernetes | 노드 하나를 선택하는 CoolingZone과 같은 노드의 Fan |

[랙 두 개](../../design/v1/examples/two-racks.yaml),
[노드별 팬](../../design/v1/examples/per-node.yaml),
[여러 팬](../../design/v1/examples/multi-fan.yaml) 예시를 제공합니다.
[커널 PWM 예시](../../design/v1/examples/sysfs.yaml)는 Pi 5의 sysfs 구성을 보여주며
overlay와 물리 채널은 실제 하드웨어에서 확인해야 합니다.

랙 두 개의 멤버십 예시:

```sh
kubectl label nodes pi-01 pi-02 pi-03 pi-04 pifanctl.jyje.online/rack=a
kubectl label nodes pi-05 pi-06 pi-07 pi-08 pifanctl.jyje.online/rack=b
```

라벨은 실제 냉각 배치를 설명합니다. 팬을 연결하거나 배선을 바꾸는 명령이
아닙니다. 팬 제어 위치는 Fan의 nodeName으로 따로 고정합니다. 선택된 노드 목록을
상태에 보여줘 잘못 붙은 라벨을 발견할 수 있게 합니다.

## 5. CRD 기반 desired state

공통 파일은 같은 Fan/CoolingZone spec을 담은 Kubernetes `v1/List`입니다.
세 번째 CRD가 아니라 검증과 planning 도구의 직렬화 형식입니다. Kubernetes
런타임 토폴로지는 항상 `Fan`과 `CoolingZone` CR로 관리합니다.

| 원본 | Desired state | 관측 상태 | 필요한 환경 |
| --- | --- | --- | --- |
| Native API | operator 차트 `extraResources` 값으로 렌더링한 Fan/CoolingZone CR | 리소스 `/status`, Event, metrics | CRD와 operator |
| 로컬 파일 | 오프라인 검증 또는 live planning용 List YAML | CLI 출력 | selector 해석에 API 필요, 로컬 PWM 제어는 미지원 |

operator 차트는 v1에서 지원하는 유일한 pifanctl 차트입니다. 차트가 operator와
CRD를 설치하고 `extraResources` 값에서 `Fan`과 `CoolingZone` 인스턴스를 렌더링합니다.
GitOps에서는 cluster 저장소의 operator Application 값으로 관리합니다. 별도 pifanctl
인스턴스 차트나 ConfigMap 토폴로지 모드는 v1에 포함하지 않습니다.
[실험용 설계 차트](../../design/v1/helm)는 지원되는 v1 설치 경로가 아닙니다.
Helm은 CRD를 자동 갱신하거나 삭제하지 않으므로 CRD 스키마 변경 절차는 별도로 둡니다.

## 6. 오퍼레이터와 worker 설계

초기 operator는 기존 Python 코드와 공유 validator/planner, 공식 Kubernetes
client를 사용합니다. 처음부터 Go와 Python의 두 구현을 유지할 근거는 없습니다.
leader election, list/watch 복구, 참조 인덱스, 멱등적인 reconcile, 낙관적 상태
갱신을 구현합니다. operator는 비특권이며 PWM을 직접 구동하지 않습니다.

1. 입력 snapshot의 필드와 참조를 검증합니다.
2. selector/이름을 Node와 UID로 해석하고 node→zone→fan 인덱스를 구성합니다.
   NotReady 노드도 기대 멤버에 남겨 둡니다.
3. 팬 참조와 물리 claim을 검사합니다. 유효하지 않은 구역은 팬의 불건전 입력으로
   처리하며 멤버가 없는 정상 구역으로 바꾸지 않습니다.
4. 팬별 정확한 멤버, telemetry, 곡선, 안전 규칙을 넣은 노드별 plan을 생성하고
   hash를 계산합니다.
5. 팬이 있는 노드마다 worker Deployment 하나를 배치합니다. replicas=1,
   Recreate, 정확한 Node affinity를 사용합니다. Node 이름과 hostname 라벨이
   같다고 가정하지 않고 실제 라벨과 Node UID를 확인합니다. 한 worker가 그 노드의
   모든 팬을 제어합니다.
6. 관리 ConfigMap에 plan을 게시합니다. worker는 파일 전체를 검증하고 원자적으로
   교체한 뒤 적용 hash, 팬 상태, heartbeat를 보고합니다.
7. 최신 generation, 적용 hash, 신선하고 완전한 온도, worker 상태를 확인한 뒤
   Ready를 설정합니다. 설정 변경으로 하드웨어 Pod를 매번 재시작하지 않습니다.

agent는 모든 참여 노드를 대상으로 비특권 DaemonSet으로 관리하거나 기존 agent를
명시적으로 재사용합니다. legacy 릴리스의 agent를 자동으로 인수/삭제하지 않습니다.
마지막 성공 센서 읽기 시간을 metrics로 제공하고 오래된 값에 새로운 시간을 붙이지
않습니다. worker에는 기본적으로 Kubernetes API 자격 증명을 넣지 않습니다.
operator 전용으로 접근을 제한한 상태/metrics endpoint를 사용합니다.

CR workload는 해당 노드의 Fan 중 사전순 첫 Fan을 primary owner로 합니다.
다른 Fan이 남아 있다면 primary Fan 삭제 전에 소유권을 옮깁니다. namespace 리소스를
cluster scope 리소스의 owner로 지정하지 않습니다.
[소유권 범위](https://kubernetes.io/docs/concepts/architecture/garbage-collection/).

Kubernetes ConfigMap은 operator가 관리하는 내부 worker plan 저장에만 사용합니다.
토폴로지 입력 API는 아닙니다. worker는 전체 새 plan을 읽고 검증한 뒤 적용합니다.
적용 hash 확인 전에는 수렴했다고 보고하지 않습니다. 지연되거나 잘못된 plan은 이전
정상 plan을 유지하고 Degraded로 표시합니다.

### 데이터와 하드웨어 안전 규칙

- 정확히 선택된 노드의 온도와 타임스탬프를 가져오고, 멤버별 유효성을 검사한 뒤
  최고 온도를 계산합니다. scalar 최대값 쿼리만으로 데이터 완전성을 판단하지 않습니다.
- scrape 시각과 센서 읽기 시각은 다릅니다.
  `pifanctl_temperature_observed_timestamp_seconds`를 추가해 성공한 읽기의 나이를
  검증합니다. 허용 clock skew를 넘는 미래 시각도 거부합니다.
- 기대 멤버 하나라도 데이터가 없거나 오래되면 그 구역의 모든 팬을 100%로 합니다.
  다른 연결 구역의 온도가 정상이어도 같습니다.
- Prometheus 장애, 비어 있는 구역, 끊긴 참조, Node 교체, 설정 상태 상실도 전체
  속도로 전환합니다. 공유 냉각에서 worker의 로컬 온도만으로 대체하지 않습니다.
- operator/API가 끊기면 마지막 멤버 목록을 유지합니다. alpha 기본 120초 heartbeat
  watchdog이 만료되면 full speed로 전환하고 새 설정 확인 이후에만 정상 제어합니다.
  operator가 관리 ConfigMap의 별도 heartbeat 파일을 주기적으로 갱신합니다. plan
  hash에는 포함하지 않습니다. 시각/Node UID를 검증하며 파일 전달 지연도 만료 시간에
  포함합니다. worker 자신의 보고 heartbeat와 구분하고 실제 전달 지연을 측정해
  timeout을 조정합니다.
- 로컬 CLI와 Pod가 공유하는 host 전체 lock으로 writer 프로세스 하나를 보장합니다.
  replicas=1과 leader election만으로 충분하지 않습니다. 기존 프로세스가 살아 있을
  가능성이 있으면 lease 만료만으로 lock을 빼앗지 않습니다.
- fan controller를 다른 노드로 옮겨 장애를 해결할 수는 없습니다. 배선은 그대로입니다.
  드라이버 시작 실패는 명확하게 보고하고 mock으로 대체하지 않습니다.
- claim을 획득한 팬은 온도 읽기나 plan 적용 전에 100%로 초기화하고 안전 조건을
  모두 확인한 후에만 duty를 낮춥니다.
- SIGTERM 등 정상 종료 시 100%를 요청하지만 노드/전원 고장에서는 PWM 유지가
  보장되지 않습니다. 독립 팬 전원과 전기적인 fail-open 동작을 실물에서 확인해야
  합니다. duty 명령은 RPM이나 실제 냉각 효과의 측정값이 아닙니다.

구역 삭제는 대체 plan의 적용을 확인하고 마무리합니다. 연결 구역이 없는 Fan은
100%로 유지합니다. 팬 삭제는 full duty와 claim 해제를 확인한 뒤 필요한 소유
workload/config만 제거합니다. 남은 구역의 끊긴 참조는 Degraded입니다. worker가
응답하지 않으면 finalizer를 대기 상태로 유지합니다. 강제 제거는 관리자의 별도
행동이며 하드웨어가 안전하다는 확인이 아닙니다.

### 상태, 모니터링, 권한

alpha는 사유를 담은 Ready condition을 구현합니다. 추가 진단 conditions인
MembersResolved, ReferencesResolved, TelemetryHealthy, HardwareClaimed,
ConfigurationApplied, Degraded는 후속 개선입니다.
상태 쓰기는 제한하고 온도 샘플마다 etcd에 기록하지 않습니다. Prometheus에는
노드 온도 이력을 유지하고 팬 duty, 구역 온도, 누락 멤버 수, failsafe 이유,
heartbeat metrics와 장애 알림을 추가합니다. 설정 hash를 무제한 metric label로
사용하지 않습니다.

[제안 RBAC](../../design/v1/operator/rbac.yaml)는 Node 읽기, CR 상태/finalizer 갱신,
operator namespace 안의 workload/config 관리만 허용합니다. CRD 생성, Node 라벨
수정, Secret 조회, namespace 생성 권한은 없습니다. finalizer를 위한 patch 권한은
RBAC만으로 metadata에 한정할 수 없으므로 앱 동작과 필요시 admission으로 제한합니다.
operator는 사용자 spec을 소유하지 않습니다. GPIO 권한은 worker에만 부여합니다.
실제 패키징에서는 NetworkPolicy, 제한된 securityContext, probes와 고정 image digest가
추가로 필요합니다.

## 7. CLI와 kubectl

다음 명령은 alpha에 구현했습니다. 설치와 제한은 런타임 매뉴얼을 확인하세요.

```sh
pifanctl topology validate topology.yaml
pifanctl topology render topology.yaml
pifanctl --context lab topology plan topology.yaml --live
pifanctl --context lab topology apply topology.yaml --dry-run
pifanctl --context lab topology apply topology.yaml
pifanctl --context lab zone list
pifanctl --context lab zone describe rack-a
pifanctl --context lab fan list
pifanctl --context lab fan watch
```

validate는 오프라인 검증, plan은 실제 노드 선택과 claim/변경 내역의 읽기 전용 확인,
apply는 Kubernetes API와 server-side apply를 사용합니다. `KUBECONFIG`,
`--kubeconfig`, `--context`를 지원합니다. kubectl을 문자열로 조합해 실행하지 않습니다.
하드웨어 worker는 operator만 관리합니다. 오프라인 검증은 가능하지만 live selector와
apply는 Kubernetes API가 필요합니다.

선택적인 `kubectl-pifanctl` wrapper로 `kubectl pifanctl fan list`도 같은 CLI를
호출합니다. 기본 `kubectl get fans,coolingzones`, describe, apply, diff, wait를
계속 사용할 수 있습니다. Argo처럼 기본 리소스 위에 검증과 좋은 출력을 제공하는
CLI를 목표로 하며 처음부터 별도 제어 서버를 추가하지 않습니다.
[Argo CLI](https://argo-workflows.readthedocs.io/en/latest/walk-through/argo-cli/).

apply는 native CR을 대상으로 합니다. GitOps 환경에서는 원본 저장소를 편집하고
operator 차트 `extraResources`에 같은 리소스를 선언할 수 있습니다. CLI가 Helm/Argo의
소유권을 강제로 가져오지 않습니다. 수동 duty와 팬 정지 명령은 안전한 override API
설계 이후로 미룹니다.

## 8. 단계별 구현과 v1 출시 조건

1. 실물 배선, 제어 노드, 핀/채널, 팬마다 식히는 보드를 조사하고 기존 그룹 쿼리를
   명시적인 CoolingZone으로 변환합니다.
2. 읽기 전용 plan을 배선과 대조합니다. 검토 중에는 기존 controller를 유지합니다.
3. freshness metric, 공유 schema/planner와 파일 입력을 구현합니다.
4. worker, host lock, hot reload, watchdog을 구현하고 Pi 4 GPIO와 Pi 5 sysfs의
   정상/강제 종료 및 전원 장애를 실물에서 검증합니다.
5. operator, 상태, finalizer, CLI와 wrapper를 구현하고 임시 클러스터의
   dry-run과 mock worker부터 확인합니다.
6. 팬별로 full duty → legacy 중단 → writer 해제 확인 → v1 실행을 순서대로 진행합니다.
   롤백은 v1 중단과 claim 해제 이후 legacy 복원 순서입니다.
7. 다음 기준이 통과한 후 v1 이미지와 차트를 출시합니다. 실제 구현 alpha와 정식 v1.0.0 출시는 분리합니다.

- [ ] 두 구역 각각 네 대의 온도가 자기 팬에만 반영됨
- [ ] 보드별 팬, 노드당 여러 팬, 여러 구역이 공유하는 팬 지원
- [ ] GitOps가 렌더링한 Fan/CoolingZone CR에서 예상 plan 생성
- [ ] 라벨 변경/노드 삭제/온도 누락/오래된 데이터가 보이고 안전 동작함
- [ ] 충돌 claim, 없는 참조, 잘못된 local 배치를 거부함
- [ ] 재시작/배포/네트워크 분리/인계 중 동시에 PWM을 쓰지 않음
- [ ] 설정과 삭제가 확인되고 operator 장애에서 watchdog이 동작함
- [ ] kubeconfig/context, server dry-run, GitOps 충돌, kubectl 사용 지원
- [ ] 상태 쓰기와 metrics의 부하를 제한하고 지원 규모를 측정해 문서화함
- [ ] Pi 4/Pi 5의 실제 전기/드라이버 동작을 확인하고 명령 duty와 냉각 보장을 구분함

초기에는 두 도메인 리소스로 시작합니다. 개별 노드 CRD, 추가 정책 객체, 별도 제어
서버는 실제 요구를 확인한 후 도입합니다.

### 실물 55°C 안정화 기록

2026-10-06, 사용자가 부하 테스트 전에 랙 팬의 정상 회전을 육안으로 확인한 뒤
`raspi-51`에 1 vCPU 제한 부하를 적용했습니다. alpha.3 worker에서 랙 최고 온도가 54–56°C 범위에 144초
동안 유지되었고, 23개 신선한 관측의 온도는 54.55–55.65°C, 요청 듀티는 50.44%로
일정했습니다. 원래 기준은 120초 동안 총 변동 폭 1°C 이하인데, 해당 구간은 1.10°C입니다. 재계산한 최장 적합 구간은 75초이므로 55°C 안정화 검증도 아직 완료되지 않았습니다. 부하 중 연속 육안
관찰 기록은 없고 RPM과 전기 PWM 파형도 측정하지 않았습니다. 50°C/60°C 목표와 고장
복구 검증은 남아 있습니다. 세부
데이터와 PDF는 [영문 실물 검증 매뉴얼](release-acceptance.md#10-2026-10-06-alpha3-55c-shared-rack-stability-run)을 참고하세요.
