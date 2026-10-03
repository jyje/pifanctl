# pifanctl v1 implementation plan

## 목표와 범위

현재 앱은 v0.2.1이다. 목표는 노드 라벨 또는 이름으로 냉각 대상을 선택하고,
CoolingZone과 물리 Fan을 YAML·ConfigMap·CRD로 관리하는 v1이다.
실제 worker, Kubernetes operator, kubeconfig-aware CLI, Helm 패키징을 구현한다.
실물 팬이나 운영 클러스터는 이 작업 중 변경하지 않는다. 자동 검증은 mock driver,
가짜 센서/Prometheus/Kubernetes API와 임시 파일을 사용한다.

처음 구현 버전은 `1.0.0-alpha.1`이다. 로컬/CI 검증과 실제 하드웨어 검증은 분리한다.
최종 v1.0.0 출시는 Pi 4/Pi 5 배선·드라이버·장애 검증을 통과한 뒤 진행한다.

## 작업 규칙

1. 아래 단계 순서대로 구현한다. 다음 단계의 초안은 선행 단계 검증을 통과하기 전
   커밋하지 않는다.
2. 단계의 하위 체크를 모두 확인한 뒤 해당 단계 자체를 대기 목록에서 제거한다.
   완료 기록에는 변경, 실제 검증 결과, 제한을 기록한다.
3. 구현과 해당 단계의 테스트, PLAN 갱신을 같은 커밋에 담는다. 커밋 후 완료 기록에
   그 커밋을 식별할 수 있는 메시지를 남긴다. 이 기록은 다음 커밋에서 SHA로 보강한다.
4. 사용자와 다른 작업의 파일은 stage하지 않는다. diff와 버전 게이트를 확인한다.
5. 실제 클러스터 적용, 팬 제어, PR 병합, 정식 릴리스는 별도 승인 대상이다.
6. 실패한 검증은 수정 후 다시 실행한다. 생략한 검증을 통과로 표시하지 않는다.
7. 중간 진행 상황을 계속 알리고, 구현에 따른 설계 변경은 문서에도 반영한다.

## 상태

- 설계/그림 PR: [#40](https://github.com/jyje/pifanctl/pull/40)
- v1 구현 로드맵: [#39](https://github.com/jyje/pifanctl/issues/39)
- 구현 브랜치: `feat/v1-topology-runtime` (PR #40 위에 쌓는 별도 PR)
- 제안 API: `pifanctl.jyje.online/v1alpha1`, cluster scoped Fan/CoolingZone
- 도해: 한영 각각 공유 팬/보드별 팬 × 정상/고온/데이터 누락/heartbeat 만료

## 대기 체크리스트

### 05. Operator: leader election과 reconciliation

- [ ] Lease 기반 leader election과 resourceVersion 충돌 처리
- [ ] Node/CR/ConfigMap 변경 감지, watch 복구와 주기적인 재동기화
- [ ] native CR 또는 지정 ConfigMap 단일 입력 모드
- [ ] 노드별 hashed plan/heartbeat ConfigMap과 고정 worker Deployment 생성
- [ ] Node의 실제 hostname 라벨, UID, required affinity, replicas=1/Recreate
- [ ] workload/config ownership 충돌 거부, 사용자 리소스 자동 인수 금지
- [ ] agent managed/reuse 모드, worker에 Kubernetes 자격 증명 미제공
- [ ] operator/API 장애 시 heartbeat 갱신 중단, worker watchdog 독립 동작
- [ ] mock API로 생성/변경/노드 교체/leader 상실/재동기화 테스트

완료 조건: operator는 PWM을 쓰지 않고, 기존 release를 몰래 인수하거나 다른
namespace/Node labels를 수정하지 않는다.

### 06. Operator: observed status와 안전한 삭제

- [ ] 적용 hash와 fresh worker report를 확인한 뒤 Ready 갱신
- [ ] generation, conditions/reason, resolved/missing nodes, fan/zone 상태
- [ ] status/Event 쓰기 rate limit, metric hash label의 무제한 증가 방지
- [ ] Fan/CoolingZone/입력 ConfigMap finalizer
- [ ] 삭제 plan 적용 및 팬 claim 해제 확인 후 finalizer 제거
- [ ] 같은 노드의 다른 팬이 남아 있으면 primary ownership 이전
- [ ] worker unreachable이면 삭제 대기, 강제 삭제는 안전 증명으로 취급하지 않음
- [ ] mock API로 느린/누락 report, 부분 삭제, 소유권 이전, dangling refs 테스트

완료 조건: 리소스를 지웠다는 API 응답과 실제 하드웨어 제어권 해제를 구분한다.

### 07. Helm, CRD, 이미지와 운영 문서

- [ ] 별도 operator chart: pinned version, replicas, input mode, resources, security
- [ ] RBAC: Node 읽기/CR status·finalizer/지정 namespace workloads로 제한
- [ ] worker-only hardware hostPath, 공유 lock directory, operator non-root
- [ ] NetworkPolicy, probes, worker report 접근, Prometheus scrape 설정
- [ ] CRD 설치/업그레이드 수명주기와 topology chart 연결
- [ ] schema/package parity, Helm lint/render/kubeconform 검증
- [ ] version gate, production chart/manifest/설치 버전 일치
- [ ] 한영 사용법, migration/rollback, 실제 구현과 미래 항목 구분

완료 조건: 존재하지 않는 image 기능을 문서로 설치하게 하지 않는다. alpha PR의
이미지는 merge/build 전에는 registry에 없다는 제한을 명시한다.

### 08. 종합 검증과 PR

- [ ] 기존 테스트와 새 테스트 모두 통과, coverage 기준 유지
- [ ] 자동 검증용 가짜 API와 mock hardware로 시나리오 검증
- [ ] CLI help/파일 입력/렌더링, charts/manifests와 문서 링크 확인
- [ ] 모든 agent-owned diff/버전/민감 정보/미완료 항목 검토
- [ ] 구현 PR 작성, 설계 PR 의존성과 이슈 연결, PR attachment
- [ ] CI 결과 확인 및 실패 수정
- [ ] 완료 기록과 최종 요약에 검증 범위를 정확하게 보고

완료 조건: 실제 구현을 검토 가능한 PR로 제공한다. 실물 검증 전 정식 v1 릴리스를
완료했다고 주장하지 않는다.

## 실제 운영에서 남을 출시 게이트

- [ ] 명시적으로 선택한 임시 Kubernetes API 서버에서 CRD/CEL/defaulting 승인 확인
- [ ] Pi 4 GPIO/ Pi 5 sysfs의 실제 배선, 채널, 초기/종료 PWM 측정
- [ ] process kill, Node 재부팅/전원 상실, 네트워크 partition 시 팬 동작 측정
- [ ] 오래된 controller를 중단한 뒤 팬별 migration/rollback 수행
- [ ] 지원 fleet 규모와 status/Prometheus/API 부하 측정
- [ ] 전기적 fail-open/독립 팬 전원 조건 문서화 후 v1.0.0 출시

## 완료 기록

| 단계 | 변경 및 검증 | 커밋 |
| --- | --- | --- |
| 사전 설계 | CRD/예시/한영 설계, PR #40 CI 성공. 아직 runtime 없음 | `e31e183` |
| 도해/버전 정정 | SVG→PNG 16쌍, 한영 README 8개 시나리오씩, v1 경로/표기. PNG 시각 확인, diff check | `dc01b03` |

| 01 | 스키마/defaults, YAML 엄격 검증, label/name planner, 충돌/failsafe와 hash. 기존 및 새 테스트 153 passed (coverage는 종합 단계). 앱/기존 chart alpha 버전 동기화 | `03290da` |

| 02 | agent read timestamp, exact-label freshness, complete zone/local floor, missing/stale/outage. 30 telemetry/service tests passed | `01e1a17` |

| 03 | worker multi-fan/full duty/reload/watchdog/report, host lock + legacy lock, GPIO thread release and chart hostPath. 182 full tests + 36 focused tests passed. Cooperative host-wide lock; real PWM remains unverified | `19c27ff` |

| 04 | official client/context, bounded API/SSA/dry-run, topology/fan/zone/worker CLI, kubectl wrapper. 188 full tests passed. Local file is compiled once; selectors require --live | `✨ feat(cli): manage cooling topology through kubernetes` |
