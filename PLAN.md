# pifanctl v1 implementation plan

## 목표와 범위

작업 시작 시 앱은 v0.2.1이었다. 목표는 노드 라벨 또는 이름으로 냉각 대상을 선택하고,
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
- 구현 브랜치: `feat/v1-topology-runtime` ([PR #41](https://github.com/jyje/pifanctl/pull/41), PR #40 위에 쌓음)
- 제안 API: `pifanctl.jyje.online/v1alpha1`, cluster scoped Fan/CoolingZone
- 도해: 한영 각각 공유 팬/보드별 팬 × 정상/고온/데이터 누락/heartbeat 만료

## 대기 체크리스트

단계 01~08의 구현·mock 검증·커밋·PR 제출을 완료하여 대기 항목을 제거했다.
아래 출시 게이트는 실제 운영 검증이 필요하므로 유지한다.

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
| 04 | official client/context, bounded API/SSA/dry-run, topology/fan/zone/worker CLI, kubectl wrapper. 188 full tests passed. Local file is compiled once; selectors require --live | `395e6fb` |
| 05 | Lease leadership, CR/ConfigMap planner, exact Node/UID worker Deployment+plan/heartbeat, protected ownership and watch/resync. 6 fake API tests passed. Agent managed/reuse deployment is packaged in stage 07 | `3aa1018` |
| 06 | observed hash/UID status, rate limits/events, finalizers, primary transfer and durable empty-plan acknowledgements. 11 fake API tests passed; unreachable worker stays pending | `b0bdc82` |
| 07 | operator chart/RBAC/NetworkPolicy/agents/CRDs, 한영 runtime/migration, alpha prerelease·latest 보호, 로컬 YAML reload·sticky member UID. Helm lint 두 입력 모드/토폴로지, kubeconform operator 9 + worker 1, actionlint, Python3.10 49 focused tests passed. CI3.10~3.14 보존 회귀 테스트 추가 | `3921b92` |
| 08-a | 다섯 Python 버전에서 218 tests/93.88~93.91%. 실제 client와 mock HTTP/공유 랙 시나리오 통합 테스트로 인자·상태 함수 충돌 수정. 마지막 견고성 수정 후 3.14 218 tests/93.48%. kubeconform K8s1.30/1.33 + actionlint 통과 | `f8e6dcb` |
| 08-b | PR #41 생성/attachment. 첫 원격 CI의 9개 job 성공. 보드별/여러 팬/watch 복구 테스트 추가 후 로컬3.14 224 tests/95.69%. 느린 조회와 독립적인 watchdog latch 추가, focused 22 tests 및 전체3.14 227 tests/95.65% passed. 조회 지연도 sample age에 반영. 해당 커밋의 원격 CI 9개 job 모두 성공 | `f08e04e` |
| 08-c | namespace/operatorId 소유권으로 다른 namespace의 동명 operator 인수 거부. 18 focused tests passed; 마지막 코드의 다섯 Python 버전 전체 검증 완료. 228 tests passed, coverage 95.66~95.68%. 해당 커밋 CI 9개 job 모두 성공 | `33f5955` |
| 08-d | ConfigMap owner-reference admission에 필요한 finalizer update를 입력 ConfigMap 한 개로 제한. Helm 렌더 12 tests/lint 및 전체3.14 228 tests/95.66%. background 삭제 경로 한영 명시. 원격 CI 9개 job 성공 | `92a142b` |
| 08 완료 | 다섯 Python 버전/90% gate 회귀 방지, 228 tests, 원격 coverage 95.72~95.74%. ARM64/chart/workflow/version 포함 9개 job 성공. 한영 README의 alpha와 두 차트 릴리스 설명 동기화. #39/#41 증거 갱신 | `📄 docs(v1): record completed runtime verification` |

### 검증 중 발견해 수정한 회귀

- Python3.10: Typer Context에 기본값 None을 둔 새 명령의 해석 실패. Context를 필수 주입 매개변수로 바꾼 뒤 전체 214 tests/92.53% 통과.
- 작업 시작 이후 main의 CI가 3.10~3.14로 확대됨. 작업 브랜치도 다섯 버전을 유지하고 matrix 회귀 테스트를 추가함. 기준은 계속 90%.

- 통합 테스트: Kubernetes36의 call_api는 response_types_map을 요구함. fake adapter만으로 놓친 인자 문제를 실제 client+가짜 HTTP에서 발견하고 수정함.
- operator HTTP snapshot과 topology snapshot의 함수명 충돌을 분리함.

## 검증 증거

- [런타임 및 RBAC 변경 CI](https://github.com/jyje/pifanctl/actions/runs/37123255182): Python3.10~3.14와 ARM64 포함 9개 job 성공.
- [이전 런타임 CI](https://github.com/jyje/pifanctl/actions/runs/37122808616): 각 버전 228 tests, coverage 95.72~95.74%.
- 로컬 macOS: Python3.10~3.14 각 228 tests, coverage 95.66~95.68%. 마지막 RBAC 변경 후3.14 전체 228 tests/95.66% 재검증.
- kubeconform은 정적 schema 검증이며 API 서버의 admission/CEL/defaulting 검증은 아니다.
- PR #40에는 설계/CRD/시나리오 SVG·PNG, PR #41에는 실제 alpha 구현과 순차 커밋이 있다. PR #40을 먼저 검토하는 stacked PR 구성이다.
