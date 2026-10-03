# pifanctl Illustration Style / 일러스트 스타일

## English

pifanctl's primary illustration is a friendly cartoon of the hardware use case: several Raspberry Pi boards in a generic open rack and cooled together by one centrally managed PWM fan. A blue whale mascot references the Kubernetes ecosystem. The artwork should make the shared rack fan easy to recognize and must not suggest a separate fan on every board. Keep the rack abstract rather than matching a particular enclosure product or brand. Identify the boards through generic PCB, GPIO header, chip, and port shapes. Do not include the Raspberry Pi berry logo or registered mark.

For clear cable access, mount the shared fan on the front face. Keep each board flat on its horizontal shelf and rotate the complete board 90 degrees within the shelf plane, so its long axis recedes into the rack and its ports face the rear, away from the fan. Cables should exit at the rear without crossing the fan or its airflow path.

Single-board fan control is also supported. The rack illustration represents the primary cluster use case, where the controller reads every node's temperature and sets the shared fan from the hottest node.

### Sticker concepts

1. Front three-quarter view, shared front fan, flat boards turned toward the rack depth, rear-facing ports, and a whale mascot with three container blocks.

   ![Cartoon rack with one shared front fan and a Kubernetes whale](pifanctl-cluster-sticker-concept-1.png)

2. Same fixed view and hardware layout, with a burgundy-accented fan ring and smaller airflow marks.

   ![Front-facing rack with one central shared fan](pifanctl-cluster-sticker-concept-2.png)

3. Same fixed view and hardware layout, with broad fan blades, a teal hub, and smooth airflow ribbons.

   ![Isometric rack with one shared top fan and whale mascot](pifanctl-cluster-sticker-concept-3.png)

### Minimalist alternative

A non-character option can reduce the same hardware idea to a few geometric shapes: a simple rack outline, several board bars, one shared fan symbol, and a clean airflow path. Use the burgundy, deep teal, pale gray, and muted pink palette from the Profile-2 site. Avoid product-specific rack details and avoid showing per-board fans.

![Minimalist pifanctl rack and shared fan mark in the Profile-2 palette](pifanctl-minimalist-cluster-mark.png)

The three sticker variants keep the same camera view, rack layout, and board orientation. Each board lies flat and turns 90 degrees within its shelf plane, with its ports and cables at the rear, away from the shared front fan. The Raspberry Pi logo and registered mark are omitted.

## 한국어

pifanctl의 대표 일러스트는 실제 하드웨어 사용 사례를 친근한 카툰으로 표현합니다. 범용 열린 랙에 여러 라즈베리 파이 보드를 설치하고, 중앙에서 제어하는 PWM 팬 하나로 함께 냉각합니다. 파란 고래 마스코트는 쿠버네티스 생태계를 나타냅니다. 특정 랙 제품이나 브랜드를 떠올리게 하는 세부 형태는 피하고, 랙 공용 팬이 명확히 보여야 하며 보드마다 팬이 따로 달린 것처럼 표현하지 않습니다. 보드는 일반적인 PCB, GPIO 핀, 칩, 포트 형태로 표현하고 파이 열매 로고나 등록 상표 마크는 넣지 않습니다.

케이블이 팬을 가리지 않도록 공용 팬은 랙 전면에 둡니다. 보드는 수평 선반 위에 평평하게 놓고, 각 보드 전체를 선반 평면에서 90도 회전해 긴 축이 랙 안쪽 깊이 방향을 향하게 합니다. 포트와 케이블은 공용 팬 반대쪽인 후면을 향하고 랙 뒤로 빠져나옵니다.

단일 보드 팬 제어도 지원합니다. 랙 그림은 클러스터의 주 사용 사례를 나타내며, 컨트롤러가 모든 노드의 온도를 읽고 가장 뜨거운 노드에 맞춰 공용 팬을 제어합니다.

세 스티커 시안은 같은 시점과 랙 배치를 유지하면서 팬 링과 공기 흐름 표현을 조금씩 바꿉니다. 세 시안 모두 수평 선반에 놓인 보드 세 대를 전면 공용 팬 하나로 함께 냉각하는 구성입니다.

### 미니멀 대안

캐릭터 없는 대안은 범용 랙 윤곽, 보드를 나타내는 몇 개의 선, 공용 팬 하나, 간결한 공기 흐름으로 같은 사용 사례를 표현합니다. Profile-2 사이트의 버건디(`#680c2c`), 짙은 청록(`#193747`), 밝은 회색(`#f3f6f7`), 차분한 분홍색(`#ba748d`) 팔레트를 사용합니다. 제품별 랙 형태와 보드별 개별 팬은 표현하지 않습니다.

[미니멀 시안 PNG 보기](pifanctl-minimalist-cluster-mark.png).

세 가지 스티커 시안은 카메라 시점, 랙 배치, 보드 방향을 고정했습니다. 보드는 수평 선반 위에 평평하게 놓고 선반 평면에서 전체를 90도 돌려 긴 축이 랙 안쪽을 향하게 했습니다. 포트와 케이블은 공용 전면 팬에서 먼 후면을 향합니다. 라즈베리 파이 로고와 등록 상표 마크는 넣지 않았습니다.
