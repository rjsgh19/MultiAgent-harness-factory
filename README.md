# Harness Automation Factory

LangGraph 기반 **Spec-driven 자율 소프트웨어 엔지니어링 공장**.

## 핵심 설계 원칙

1. **3대 실속형 에이전트**: Planner / Engineer / Reviewer (합의 노드 제거, 책임 명확화).
2. **State Hell 방지**: traceback은 `storage/traces/` 외부 파일로, State에는 경로만.
3. **Docker 격리 샌드박스**: 생성된 코드는 절대로 호스트에서 실행되지 않는다.
4. **Spec-driven Drift Detection**: AST 추출 → YAML 명세 역검증.
5. **Prompt Contract 검증**: Pydantic 스키마로 마크다운 가이드 위변조 차단.
6. **구간 기반 패치**: `# BEGIN GENERATED` ~ `# END GENERATED`만 덮어씀 — 인간 수정 영역 보호.
7. **디터미니스틱 리플레이**: `temperature=0` 강제 + 스냅샷 저장.

## Quick Start

```bash
pip install -e ".[dev]"
python -m harness_engine.graph.workflow
```

자세한 명령은 `CLAUDE.md` 참조.
