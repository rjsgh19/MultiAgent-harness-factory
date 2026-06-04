# 프로젝트명: BIM 자동 설계 시스템 (Master Workflow)

## 도메인
bim_automation_factory

## 개요
pyRevit 클라이언트와 통신하여, 사용자 설정값과 사전 잠금(Pre-Locking)된 룸 객체를 바탕으로 1단계(매스) → 2단계(구조체) → 3단계(동선/내부배치) 순서로 설계를 자동화하는 다중 에이전트 파이프라인. (현재 1, 2단계는 빈 더미 함수로 Bypass 처리되며, 전체 파이프라인 구축을 목표로 함)

## 도메인 함수
| 함수명 | 파라미터 | 반환 | docstring 필수 |
|--------|----------|------|:--------------:|
| build_initial_state | client_data: dict | dict | ✓ |
| generate_mass_layout | state: dict | dict | ✓ |
| generate_structure_layout | state: dict | dict | ✓ |
| generate_spatial_layout | state: dict | dict | ✓ |
| bake_final_elements | state: dict | dict | ✓ |

## 인바리언트
| ID | 설명 | 검증방법 | 값 |
|----|------|----------|----|
| INV-BIM-001 | Payload JSON은 version, locked_rooms, layout_alternatives 키를 가져야 함 | required_keys | version, locked_rooms, layout_alternatives |

## 워크플로 단계
| 단계 | 노드 | 실패 시 |
|------|------|---------|
| init | build_initial_state | - |
| phase1_mass | generate_mass_layout | build_initial_state |
| phase2_struct | generate_structure_layout | generate_mass_layout |
| phase3_interior | generate_spatial_layout | generate_structure_layout |
| finalize | bake_final_elements | generate_spatial_layout |

## 라우팅 규칙
| 조건 | 다음 | 페이로드 |
|------|------|----------|
| phase1_done | phase2_struct | state |
| phase2_done | phase3_interior | state |
| phase3_done | finalize | state |

## 에이전트
| 이름 | 역할 요약 | 금지 행위 | 출력 키 |
|------|-----------|-----------|---------|
| build_initial_state | pyRevit 데이터(패밀리, 공간, 잠금객체) 초기 파싱 | 데이터 변형 금지 | state |
| generate_mass_layout | 매스 도출 (현재 입력값을 그대로 Bypass) | - | layout_alternatives |
| generate_structure_layout | 뼈대 도출 (현재 입력값을 그대로 Bypass) | - | layout_alternatives |
| generate_spatial_layout | 내부 배치 도출 (현재 입력값을 그대로 Bypass) | - | layout_alternatives |
| bake_final_elements | 최종 객체 변환 데이터 및 리포트 출력 정리 | - | final_bake_data, report |

## 테스트 요구사항
| 유형 | 파일명 | 검증 내용 |
|------|--------|-----------|
| unit | test_pipeline_bypass.py | 1, 2, 3단계 에이전트가 에러 없이 Bypass 되며 State가 유지되는지 확인 |
