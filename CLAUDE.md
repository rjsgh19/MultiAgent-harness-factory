# CLAUDE.md — 개발 명령어 및 빌드 규격서

이 파일은 Claude Code가 본 저장소에서 작업할 때 참조하는 메인 명령어/빌드 규격이다.
절대 규칙은 `.clauderules`에 정의되어 있다 (반드시 함께 참조).

## Project Overview

**Harness Automation Factory** — LangGraph 기반 Spec-driven 자율 소프트웨어 공장.
3대 에이전트(Planner / Engineer / Reviewer)가 명세서 → 검증 → 계획 → 생성 → 검증 → 수리
파이프라인을 원자적으로 수행하여 최종 산출물을 `my-harness-platform/`에 드롭한다.

## Repository Layout (요약)

- `harness_engine/` — LangGraph 오케스트레이션 코어 (graph, agents, services, state).
- `agent_runtime/` — 벤더 비종속 추상화 레이어 (memory, specifications, policy_engine).
- `infrastructure/adapters/` — Claude / OpenAI / Aider 어댑터 (외부 SDK는 여기서만 import).
- `storage/` — traces, replays, telemetry 격리 저장소.
- `my-harness-platform/` — 최종 자동 생성 결과물 (src + tests).
- `docs/agent_guides/` — 에이전트 노드에 주입되는 마크다운 지시서.

## Development Commands

```bash
# 의존성 설치
pip install -e ".[dev]"

# 정적 검사
ruff check .
mypy harness_engine agent_runtime infrastructure

# 테스트 (생성된 산출물 대상)
pytest my-harness-platform/tests -v

# 샌드박스 채점 (Docker 필수)
python -m harness_engine.services.sandbox_runner

# LangGraph 워크플로우 실행
python -m harness_engine.graph.workflow
```

## Build & Quality Gates

1. 모든 커밋은 `.husky/pre-commit` 훅을 통과해야 한다 (lint + 단위 테스트).
2. GitHub Actions(`.github/workflows/ci.yml`)는 push/PR 시 전체 테스트 하네스를 가동한다.
3. 생성물은 `my-harness-platform/.generated_manifest.json`의 SHA-256 해시와 일치해야 한다.

## Coding Conventions

- Python 3.11+, 타입 힌트 필수, `from __future__ import annotations` 권장.
- 도메인 레이어(`my-harness-platform/src/domain/`)는 외부 의존성 0%.
- 모든 노드 전환 시 `services/telemetry.py`를 통해 Structured Log + Trace ID 기록.

## Atomic Pipeline (반드시 준수)

```
Spec Load → Prompt Contract Validate → Planner →
Engineer (코드 생성) → drift_detector (AST 명세 대조) →
sandbox_runner (Docker 격리 채점) →
[PASS]→ artifact_writer (구간 기반 패치 + manifest 갱신) →
[FAIL]→ Planner (실패 분석) → Engineer (자가 치유)
[3회 초과 / SECURITY_VIOLATION / INFRA_TIMEOUT / SPEC_DRIFT] → HITL interrupt()
```

## Safety Reminders

- 본 저장소에서 코드 생성을 수행할 때 `.clauderules`의 모든 항목을 우선시한다.
- 생성된 산출물 영역(`my-harness-platform/`)을 수정할 때는 반드시
  `# BEGIN GENERATED` ~ `# END GENERATED` 구간만 건드린다.
