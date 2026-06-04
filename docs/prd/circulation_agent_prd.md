# 프로젝트명: 동선(Spine-First) 내부 배치 에이전트

## 도메인
bim_circulation_agent

## 개요
미리 정의된 다중 동선 네트워크(여객, 소방, BF)의 노드들을 최단 거리(A*)로 연결하여 통로(Spine)를 뚫고, 남은 공간에 Optuna를 활용하여 룸(Room)들을 최적 배치하는 시스템. 고정 장애물과 잠긴 방(Locked Rooms)을 피해야 하며, 방의 용도에 따라 특정 동선과의 인접도 점수를 계산하여 최적화한다.

## 도메인 함수
| 함수명 | 파라미터 | 반환 | docstring 필수 |
|--------|----------|------|:--------------:|
| build_base_grid | data: dict | tuple(np.ndarray, int, int) | ✓ |
| build_corridor_masks | grid_base: np.ndarray, data: dict | tuple(dict, dict) | ✓ |
| optimize_room_placements | ctx: dict | dict | ✓ |
| evaluate_placements | placements: list, ctx: dict | dict | ✓ |
| generate_visual_report | data: dict, grid_base: np.ndarray, masks: dict, placements: list, paths: dict | str | ✓ |

## 인바리언트
| ID | 설명 | 검증방법 | 값 |
|----|------|----------|----|
| INV-CIRC-001 | 입력 Payload는 필수 키를 모두 포함해야 함 | required_keys | project_boundary, fixed_obstacles, locked_rooms, spine_networks, rooms_to_place, optimization_weights |
| INV-CIRC-002 | 배치된 방들은 외곽선(Boundary)을 벗어나면 안 됨 | out_of_bounds_check | 0 (위반 없음) |
| INV-CIRC-003 | 배치된 방들은 장애물(Obstacles)이나 통로(Spine) 영역을 침범하면 안 됨 | overlap_penalty | 0 (치명적 겹침 없음) |
| INV-CIRC-004 | 배치된 방끼리 서로 겹쳐서는 안 됨 | intersection_check | 0 (교차 없음) |

## 워크플로 단계
| 단계 | 노드 | 실패 시 |
|------|------|---------|
| init_grid | build_base_grid | - |
| route_spine | build_corridor_masks | init_grid |
| pack_rooms | optimize_room_placements | route_spine |
| review_layout | evaluate_placements | pack_rooms |
| finalize_report | generate_visual_report | review_layout |

## 라우팅 규칙
| 조건 | 다음 | 페이로드 |
|------|------|----------|
| grid_built | route_spine | state + grid |
| spine_routed | pack_rooms | state + masks |
| rooms_packed | review_layout | state + placements |
| evaluation_pass | finalize_report | state |
| evaluation_fail | pack_rooms | penalty_feedback |

## 에이전트
| 이름 | 역할 요약 | 금지 행위 | 출력 키 |
|------|-----------|-----------|---------|
| SpineRouter | A* 알고리즘을 사용해 여객/소방/BF 동선 통로 마스크 생성 | 장애물(Obstacle) 관통 | corridor_masks, paths |
| RoomPacker | Optuna(TPESampler)를 이용해 통로 외의 빈 공간에 방 배치 (면적/비율 준수) | 영역 밖(OOB) 배치 | placements, scores |
| LayoutEvaluator | RoomPacker의 결과물이 인바리언트를 위반했는지 최종 검수 | 데이터 변형 | is_valid, feedback |

## 테스트 요구사항
| 유형 | 파일명 | 검증 내용 |
|------|--------|-----------|
| unit | test_spine_router.py | A* 경로가 장애물을 회피하며 두 노드를 연결하는지 확인 |
| unit | test_room_packer.py | 생성된 방의 너비/높이가 min_area, max_aspect_ratio 조건을 만족하는지 확인 |
| intg | test_circulation_workflow.py | test_data.json을 주입했을 때 오류 없이 최종 리포트가 생성되는지 종단 검사 |

## 페이로드 스키마 (입력 JSON 구조)
에이전트가 파싱해야 할 `state` 데이터(JSON)의 정확한 구조는 다음과 같습니다.
```json
{
  "project_boundary": {"width": int, "height": int},
  "fixed_obstacles": [
    {"type": "wall|column", "name": str, "coords": [[x1, y1], [x2, y2]]}
  ],
  "locked_rooms": [
    {"id": str, "name": str, "coords": [[x1, y1], [x2, y2]]}
  ],
  "spine_networks": {
    "passenger": { "nodes": [{"name": str, "coord": [x, y]}], "width": int },
    "fire_evac": { "nodes": [{"name": str, "coord": [x, y]}], "width": int },
    "bf_barrier_free": { "nodes": [{"name": str, "coord": [x, y]}], "width": int }
  },
  "optimization_weights": {
    "passenger_weight": float, "fire_evac_weight": float, "bf_weight": float
  },
  "rooms_to_place": [
    {
      "id": str, "name": str, 
      "min_area": int, "max_area": int, "max_aspect_ratio": float, 
      "requires_bf": bool
    }
  ]
}
```
