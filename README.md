# Harness Automation Factory

LangGraph 기반 **Spec-driven 자율 소프트웨어 엔지니어링 공장**입니다.

어떤 프로젝트든 **PRD(제품 요구사항 정의서) 마크다운 문서** 하나만 작성해서 이 공장에 넣으면, 
해당 시스템을 처음부터 생성하고 검증할 수 있는 코드 뼈대, 에이전트 가이드, YAML 명세서, 테스트 스캐폴드를 100% 자동 생성해 줍니다.

---

## ✨ 주요 기능

1. **PRD 기반 원클릭 공장 세팅**
   - 도메인 특화 PRD(Markdown)를 LLM이 100% 동적 파싱하여 프로젝트 규격을 추출합니다.
   - 추출된 규격을 바탕으로 도메인 명세서(YAML), 워크플로 명세서(YAML), 에이전트 가이드(MD), 단위 테스트 스캐폴드(Python)를 자동 생성합니다.
2. **3대 실속형 공장 에이전트 (Planner / Engineer / Reviewer)**
   - 생성된 명세서를 바탕으로 **코드 변경 계획 수립 → 코드 작성(패치) → 샌드박스 품질 판정** 파이프라인을 원자적으로 수행합니다.
3. **Spec-driven Drift Detection (명세 기반 오류 탐지)**
   - AST(추상 구문 트리)를 추출하여 생성된 코드가 YAML 명세서와 1:1로 일치하는지 역검증합니다.
4. **Docker 격리 샌드박스**
   - 생성된 코드는 호스트가 아닌 격리된 Docker 컨테이너 내부에서 실행 및 채점되어 100% 보안을 보장합니다.

---

## 🛡️ 8대 핵심 설계 원칙 및 아키텍처 (Core Principles)

이 공장은 단순 코드 생성을 넘어 **화이트해커 수준의 가상 샌드박싱**, **AST 정밀 역분석을 통한 명세 정렬**, **인간 수동 코드 보존 보호 메커니즘**을 결합한 엔터프라이즈급 아키텍처 원칙을 준수하여 설계되었습니다.

| 원칙 및 목표 | 핵심 구현 방식 및 효과 | 관련 모듈/파일 |
| :--- | :--- | :--- |
| **1. 런타임 추상화**<br>*(Runtime Abstraction)* | 외부 LLM 연동 코드를 완벽 분리하고 `LLMAdapter` Protocol 인터페이스를 구축하여 벤더 결합도 0%를 달성했습니다. | [infrastructure/adapters/](./infrastructure/adapters/) |
| **2. 3대 에이전트 구조**<br>*(Multi-agent Consolidation)* | 합의 병목을 유발하는 에이전트 다자 구조를 전면 통합하여 역할이 명확한 3대 핵심 에이전트로 단순화 및 최적화했습니다. | [Planner](./harness_engine/agents/planner.py) \| [Engineer](./harness_engine/agents/engineer.py) \| [Reviewer](./harness_engine/agents/reviewer.py) |
| **3. State Hell 방지**<br>*(State Optimization)* | 무거운 pytest 에러 traceback은 물리 파일로 격리 저장하며, State에는 오직 240자 요약본과 상대 경로만 담아 메모리 폭주를 차단합니다. | [storage/traces/](./storage/traces/)<br>[state/failure_types.py](./harness_engine/state/failure_types.py) |
| **4. 보안 샌드박스**<br>*(Docker Isolation)* | 생성 코드를 격리된 Docker 컨테이너에서 pytest 채점합니다. CPU 50%, RAM 512MB 제한, 네트워크 차단, read-only root 마운트로 호스트를 격리 보호합니다. | [services/sandbox_runner.py](./harness_engine/services/sandbox_runner.py) |
| **5. AST 이탈 역추적**<br>*(Drift Detection)* | 생성 코드의 AST(추상 구문 트리)를 추출하여 YAML 명세(Arity, params, docstring, forbidden_imports)와 불일치 시 `SPEC_DRIFT`로 즉시 차단합니다. | [services/drift_detector.py](./harness_engine/services/drift_detector.py) |
| **6. 프롬프트 안전 계약**<br>*(Prompt Contract)* | Pydantic 기반 계약 검사로 가이드 크기를 64KB로 제한하며, 악성 인젝션 패턴(Trojan Unicode, ANSI, script) 감지 시 즉각 실행을 거부합니다. | [services/prompt_loader.py](./harness_engine/services/prompt_loader.py) |
| **7. 구간 기반 안전 패치**<br>*(Artifact Guard)* | `# @generated`가 없는 인간 작성 영역 덮어쓰기를 원천 방지하며, `# BEGIN/END` 마커 내부만 국소 패치합니다. 매니페스트 해시 검증으로 외부 임의 수정을 차단합니다. | [services/artifact_writer.py](./harness_engine/services/artifact_writer.py) |
| **8. 관측성 & 리플레이**<br>*(Observability & Replay)* | `temperature=0.0`을 강제하여 완전한 결정성을 지키며, 모든 입출력의 스냅샷을 물리 파일로 저장해 실패 상황의 100% 리플레이 능력을 보장합니다. | [services/replay_store.py](./harness_engine/services/replay_store.py)<br>[services/telemetry.py](./harness_engine/services/telemetry.py) |

---

## 📂 디렉토리 구조

```text
.
├── .claude/
│   └── skills/              # PRD 파싱 및 공장 자동화 스크립트 (prd_to_factory.py 등)
├── agent_runtime/           # [공장] 벤더 비종속 추상화 레이어 (memory, specifications)
├── docs/
│   ├── prd/                 # 사용자가 작성할 PRD 마크다운 문서들
│   └── agent_guides/        # 각 에이전트 노드에 주입될 마크다운 지시서 (자동 생성됨)
├── harness_engine/          # [공장] LangGraph 오케스트레이션 코어 (graph, agents, services)
├── infrastructure/          # [공장] Claude / OpenAI 외부 LLM 어댑터
├── my-harness-platform/     # [최종 산출물] 공장이 만들어낸 결과물(src, tests)이 드롭되는 곳
└── storage/                 # 시스템 동작 로그, traces, replays, telemetry 격리 저장소
```

---

## 🚀 빠른 시작 (Quick Start)

### 1. 환경 설정

```bash
# 의존성 설치
pip install -e ".[dev]"
```

최상위 경로에 `.env` 파일을 생성하고 LLM API 키를 입력합니다 (Claude 기반 권장).
```env
ANTHROPIC_API_KEY="sk-ant-..."
# 또는 OPENAI_API_KEY="sk-..."

# [선택] 샌드박스 실행 환경 토글 (기본값: true)
# true: Docker 샌드박스에서 격리 테스트 진행 (Docker Desktop 필요)
# false: 로컬 윈도우/호스트 환경에서 직접 pytest 진행 (pyRevit 등 로컬 의존성 프로젝트에 적합)
USE_DOCKER=false

# [필수] 현재 가동할 타겟 도메인(Micro-PRD) 이름
# 공장 가동 시 agent_runtime/specifications/ 아래의 어떤 사양서를 읽을지 결정합니다.
# ❌ 틀린 예: TARGET_DOMAIN=my_project_domain_spec.yaml (확장자 포함 금지)
# ⭕ 바른 예: TARGET_DOMAIN=my_project (접두사만 입력)
TARGET_DOMAIN=pre_locking_agent
```
*(주의: 공장 가동 시 의존성 누락 에러가 발생한다면, 터미널에서 `pip install -e .` 명령어를 실행하여 필수 패키지(`python-dotenv`, `docker`, `anthropic` 등)를 한 번에 설치할 수 있습니다.)*

### 2. PRD 문서로 산출물 자동 생성

준비된 PRD 마크다운 문서를 입력으로 주어 공장 가동을 위한 뼈대를 10여초 만에 생성합니다.
```bash
# 실제 문서 생성
python .claude/skills/prd_to_factory.py --prd docs/prd/my_project_prd.md

# 미리보기 (실제 쓰기 없이 파싱 결과만 확인)
python .claude/skills/prd_to_factory.py --prd docs/prd/my_project_prd.md --dry-run
```

### 3. 하네스 엔진(공장) 가동

산출물 세팅이 완료되면 3대 에이전트 루프를 실행하여 실제 코드를 작성하고 샌드박스에서 검증합니다.
```bash
python -m harness_engine.graph.workflow
```

---

## 📄 PRD 작성 가이드 (템플릿)

이 공장이 코드를 정확히 생성하려면 PRD 파일(`docs/prd/my_project_prd.md`) 내에 **반드시 표 형태**로 다음 내용이 포함되어야 합니다.

- **도메인 함수**: 에이전트들이 호출할 도메인 로직의 시그니처 (이름, 파라미터, 반환형)
- **인바리언트**: 시스템 불변식 (필수 JSON 키, 정규식 등 데이터 검증 기준)
- **워크플로 / 라우팅 규칙**: LangGraph 상태 머신의 노드 흐름
- **에이전트**: 에이전트 역할과 출력 JSON 스키마
- **테스트 요구사항**: TDD를 위한 검증 리스트

<details>
<summary>💡 PRD 예시 템플릿 보기 (클릭하여 펼치기)</summary>

```markdown
# 프로젝트명: Example Project

## 도메인
example_domain

## 도메인 함수
| 함수명 | 파라미터 | 반환 | docstring 필수 |
|--------|----------|------|:--------------:|
| generate_layout | state: dict, user_instruction: str | dict | ✓ |
| score_compliance | layout: dict, regulations: dict | dict | ✓ |

## 인바리언트
| ID | 설명 | 검증방법 | 값 |
|----|------|----------|----|
| INV-EX-001 | Payload JSON은 version, elements 키 필수 | required_keys | version, elements |

## 워크플로 단계
| 단계 | 노드 | 실패 시 |
|------|------|---------|
| input_generation | parse_instruction, generate_layout | - |
| audit | score_compliance | generate_layout |

## 라우팅 규칙
| 조건 | 다음 | 페이로드 |
|------|------|----------|
| any_auditor_fail | generate_layout | merged_feedback |

## 에이전트
| 이름 | 역할 요약 | 금지 행위 | 출력 키 |
|------|-----------|-----------|---------|
| generate_layout | 유일한 Layout 생성자 | 법규 수치 직접 계산 금지 | layout, self_check |
| score_compliance | 법규 이격 채점관 | state 직접 수정 금지 | verdict, violations |

## 테스트 요구사항
| 유형 | 파일명 | 검증 내용 |
|------|--------|-----------|
| unit | test_layout_schema.py | Layout JSON 스키마 반영 확인 |
```
</details>

---

## 🔄 Micro-PRD 기반 점진적 설계 워크플로우 (Bottom-Up)

하네스 공장에 거대한 '통합 PRD'를 한 번에 완벽하게 설계하여 입력하기보다는, **기능 단위로 쪼갠 Micro-PRD를 기반으로 먼저 공장을 가동하여 코드를 점진적으로 구현한 뒤, 완성된 구조에 맞추어 메인 명세를 역으로 동기화하는 상향식(Bottom-Up) 기획 방식**을 사용합니다. 

### 📝 단계별 작업 절차 (Bottom-Up 기획 방식)

1. **가벼운 전체 뼈대 작성 (Main-PRD 골격)**
   - 백지 상태에서 시작하기보다는, 프로젝트 전체 목표와 예상되는 큰 워크플로우(어떤 에이전트들이 어느 순서로 실행될지)를 담은 아주 가벼운 `master_workflow_prd.md`를 먼저 작성해 둡니다. 구체적인 데이터 규격이나 로직은 비워둡니다.
2. **Micro-PRD 작성 및 하네스 가동 (기능별 바텀업)**
   - 당장 구현하고자 하는 모듈/에이전트의 세부 요구사항을 담은 Micro-PRD(예: `docs/prd/01_pre_locking_agent_prd.md`)를 작성합니다.
   - **중요:** 하네스 공장을 가동하기 직전, `.env` 파일의 `TARGET_DOMAIN` 값을 현재 작업하려는 타겟으로 직접 변경해 줍니다. (주의: `_domain_spec.yaml`을 제외한 접두사만 입력해야 합니다. 예: `pre_locking_agent`)
   - 스크립트를 실행하여 작성된 Micro-PRD를 하네스 공장에 주입하고 코드를 자동 생성 및 패치합니다.
3. **PRD 기반 피드백 및 코드 고도화**
   - 코드가 생성된 후 의도와 다르다면, 코드를 직접 수정하는 대신 **Micro-PRD의 제약 조건과 인바리언트를 수정**하여 공장을 다시 돌림으로써 코드를 고도화합니다.
4. **Main-PRD 및 명세 역동기화**
   - 개별 기능의 구현이 완료되거나 인터페이스가 구체화되면, AI 에이전트에게 "구현된 결과물과 Micro-PRD 구조에 맞게 Main-PRD(`docs/prd/master_workflow_prd.md`)와 연동 사양을 수정해줘"라고 요청합니다.
   - 전체 시스템 구조와 에이전트 간 공용 컨텍스트(`ctx`)의 연결성을 Main-PRD에 최종 반영합니다.
5. **통합 공장 가동 (Auto-Wiring)**
   - 메인 명세 갱신이 끝나면, `.env`의 타겟을 `TARGET_DOMAIN=master_workflow` (또는 해당 메인 타겟명)로 변경하고 공장을 마지막으로 가동합니다.
   - 공장이 개별 에이전트들을 하나로 묶어주는 슈퍼바이저(Supervisor) 라우팅 로직을 자동 생성하여 전체 시스템을 완성(조립)합니다.

---

## 🛠️ 코드 수정 및 유지보수 (Drift Detection & Patching)

이 프로젝트는 코드를 직접 수동으로 건드리는 대신, **PRD 명세서만 수정하고 하네스 공장을 다시 가동하여 코드를 외과 수술하듯 패치하는 방식(PRD-Driven)**을 따릅니다.

1. **Drift Detection (차이 탐지)**: 공장을 가동하면 `Reviewer` 에이전트가 현재 작성된 파이썬 코드의 AST(추상 구문 트리)를 분석하여 YAML 명세서와의 불일치를 찾아냅니다.
2. **안전한 구간 기반 패치**: `Engineer` 에이전트는 코드 내의 `# BEGIN GENERATED` 와 `# END GENERATED` 특수 마커 사이의 구역만 타겟팅하여 안전하게 코드를 패치합니다.

---

## ⚙️ 아키텍처 및 역할 구분

이 저장소는 어플리케이션을 직접 서비스하는 것이 아니라, **어플리케이션을 만들어내는 공장**입니다.

### 공장(Factory) vs 애플리케이션 에이전트
| 구분 | 에이전트 | 역할 |
|------|----------|------|
| **공장** (이 저장소) | Planner | YAML 명세 + 실패 로그 → 변경 **계획** JSON |
| | Engineer | 계획 → `my-harness-platform/` **코드 패치** (안전한 구간 기반 패치) |
| | Reviewer | drift + sandbox + spec → **PASS/FAIL** 판단 |
| **애플리케이션** (생성 대상 예시) | Supervisor | 라우팅·취합·재설계 루프 (PRD에 따라 동적 구성) |
| | Task Agent | 도메인별 실제 작업 수행자 (PRD에 따라 동적 구성) |
| | Evaluator | 작업 결과물 검증/채점자 (수정 권한 없음) |

> 공장은 대상 시스템의 코드와 에이전트 가이드 마크다운을 찍어내고, 그렇게 생성된 대상(애플리케이션) 에이전트들은 도메인에 특화된 데이터 구조(JSON)를 주고받으며 자신들의 목적을 달성하게 됩니다.
