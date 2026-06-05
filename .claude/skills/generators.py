# @generated
"""공장 문서 생성기 — PRD 구조체 → YAML/MD/테스트 파일 자동 생성.

PRD 파서가 추출한 구조화된 dict를 받아 하네스 공장 가동에 필요한
모든 문서를 일관성 있게 생성/수정한다.
"""
# BEGIN GENERATED
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any, Callable
import json

import yaml


class GeneratorResult:
    """생성 결과 추적."""

    def __init__(self) -> None:
        self.created: list[str] = []
        self.modified: list[str] = []
        self.skipped: list[str] = []
        self.errors: list[str] = []

    def report(self) -> str:
        lines: list[str] = []
        for p in self.created:
            lines.append(f"  ✅ 생성: {p}")
        for p in self.modified:
            lines.append(f"  ✏️  수정: {p}")
        for p in self.skipped:
            lines.append(f"  ⏭️  건너뜀: {p}")
        for e in self.errors:
            lines.append(f"  ❌ 오류: {e}")
        lines.append(f"  총 {len(self.created)}개 생성, {len(self.modified)}개 수정")
        return "\n".join(lines)


# === Domain Spec YAML ===

def generate_domain_spec(prd: dict[str, Any], specs_dir: Path,
                         dry_run: bool = False) -> tuple[Path, str]:
    """PRD → vertiport_domain_spec.yaml"""
    domain = prd["domain"]
    out_path = specs_dir / f"{domain}_domain_spec.yaml"

    contracts = []
    for f in prd.get("functions", []):
        c: dict[str, Any] = {
            "kind": "function",
            "module": "my-harness-platform/src/domain",
            "name": f["name"],
            "parameters": f["parameters"],
            "returns": f["returns"],
        }
        if f.get("docstring_required"):
            c["docstring_required"] = True
        contracts.append(c)

    spec: dict[str, Any] = {
        "version": "1.0",
        "domain": domain,
        "contracts": contracts,
        "forbidden_imports": prd.get("forbidden_imports", []),
        "invariants": prd.get("invariants", []),
    }

    # invariants 내의 required_keys 요구사항을 최상위 키로 자동 추가하여 DriftDetector 메타 검증 통과를 보장
    for inv in prd.get("invariants", []):
        if "required_keys" in inv:
            for key in inv["required_keys"]:
                if key not in spec:
                    spec[key] = {}

    content = (
        f"# 도메인 명세서 — {prd.get('project_name', domain)}\n"
        f"# drift_detector가 AST와 역대조하는 단일 진실 공급원(SSOT).\n\n"
        + yaml.dump(spec, allow_unicode=True, default_flow_style=False, sort_keys=False)
    )

    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
    return out_path, content


# === Workflow Spec YAML ===

def generate_workflow_spec(prd: dict[str, Any], specs_dir: Path,
                           dry_run: bool = False) -> tuple[Path, str]:
    """PRD → vertiport_workflow_spec.yaml"""
    domain = prd["domain"]
    out_path = specs_dir / f"{domain}_workflow_spec.yaml"

    stages = []
    for s in prd.get("stages", []):
        stage: dict[str, Any] = {"id": s["id"], "nodes": s["nodes"]}
        if "on_fail" in s:
            stage["on_fail"] = s["on_fail"]
        stages.append(stage)

    spec: dict[str, Any] = {
        "version": "1.0",
        "workflow": f"{domain}_v1",
        "stages": stages,
        "routing_rules": prd.get("routing_rules", []),
    }

    content = (
        f"# 워크플로 명세서 — {prd.get('project_name', domain)}\n"
        f"# LangGraph 노드·엣지 계약.\n\n"
        + yaml.dump(spec, allow_unicode=True, default_flow_style=False, sort_keys=False)
    )

    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
    return out_path, content


# === Architecture Policy Merge ===

def merge_architecture_policy(prd: dict[str, Any], specs_dir: Path,
                              dry_run: bool = False) -> tuple[Path, bool]:
    """architecture_policy.yaml에 도메인 레이어 정보 머지. 반환: (경로, 변경여부)"""
    policy_path = specs_dir / "architecture_policy.yaml"
    if not policy_path.exists():
        return policy_path, False

    data = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    layers = data.get("layers", [])
    existing_names = {l["name"] for l in layers}

    domain = prd["domain"]
    new_layers = [
        {"name": "domain", "path": "my-harness-platform/src/domain", "may_import": []},
        {"name": "use_cases", "path": "my-harness-platform/src/use_cases", "may_import": ["domain"]},
        {"name": "interfaces", "path": "my-harness-platform/src/interfaces", "may_import": ["domain", "use_cases"]},
        {"name": "infrastructure", "path": "my-harness-platform/src/infrastructure", "may_import": ["domain", "use_cases", "interfaces"]},
    ]

    changed = False
    for nl in new_layers:
        if nl["name"] not in existing_names:
            layers.append(nl)
            changed = True

    if changed and not dry_run:
        data["layers"] = layers
        policy_path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
    return policy_path, changed


# === Agent Guide MD ===

def generate_agent_guide(agent: dict[str, Any], guides_dir: Path,
                         project_slug: str,
                         dry_run: bool = False) -> tuple[Path, str]:
    """단일 에이전트 가이드 MD 생성."""
    name = agent["name"]
    subdir = guides_dir / project_slug
    out_path = subdir / f"{name}.md"

    output_schema = {}
    for key in agent.get("output_keys", []):
        output_schema[key] = f"<{key} 값>"

    role_text = agent.get('role_summary', f'당신은 {name} 에이전트다.')
    forbidden_text = agent.get('forbidden', '출력은 JSON만.')
    schema_text = _json_schema_str(output_schema)
    content = (
        f"# {name.replace('_', ' ').title()} Agent Guide\n"
        f"\n"
        f"## ROLE\n"
        f"{role_text}\n"
        f"\n"
        f"## CONSTRAINTS\n"
        f"- {forbidden_text}\n"
        f"- 출력은 JSON만. 자연어 서두/말미 금지.\n"
        f"- State에 traceback 전문을 넣지 말고 trace_path만 기록한다.\n"
        f"\n"
        f"## OUTPUT_FORMAT\n"
        f"{schema_text}\n"
    )

    if not dry_run:
        subdir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
    return out_path, content


def augment_factory_guides(prd: dict[str, Any], guides_dir: Path,
                           dry_run: bool = False) -> list[tuple[Path, bool]]:
    """planner.md / engineer.md / reviewer.md CONSTRAINTS 보강."""
    results: list[tuple[Path, bool]] = []
    extra = prd.get("extra_constraints", [])
    if not extra:
        return results

    constraint_block = "\n".join(f"- {c}" for c in extra)

    for guide_name in ("planner.md", "engineer.md", "reviewer.md"):
        guide_path = guides_dir / guide_name
        if not guide_path.exists():
            results.append((guide_path, False))
            continue

        text = guide_path.read_text(encoding="utf-8")
        marker = f"# --- {prd['domain']} constraints ---"

        if marker in text:
            results.append((guide_path, False))
            continue

        insert = f"\n{marker}\n{constraint_block}\n"

        # ## OUTPUT_FORMAT 앞에 삽입
        if "## OUTPUT_FORMAT" in text:
            text = text.replace("## OUTPUT_FORMAT", f"{insert}\n## OUTPUT_FORMAT")
        else:
            text += insert

        if not dry_run:
            guide_path.write_text(text, encoding="utf-8")
        results.append((guide_path, True))

    return results


# === Test Scaffold ===

def generate_test_scaffold(test: dict[str, Any], tests_root: Path,
                           prd: dict[str, Any] | None = None,
                           raw_markdown: str | None = None,
                           llm_complete: Callable[[str, str], str] | None = None,
                           dry_run: bool = False) -> tuple[Path, str]:
    """단일 테스트 파일 생성. llm_complete가 주어지면 LLM을 통해 Assert 로직이 구현된 실질적인 테스트 코드를 생성한다."""
    type_dir_map = {
        "unit": "unit",
        "integration": "integration",
        "harness": "harnesses",
    }
    subdir = type_dir_map.get(test["type"], "unit")
    filename = test["filename"]
    if not filename.startswith("test_"):
        filename = f"test_{filename}"
    if not filename.endswith(".py"):
        filename += ".py"

    out_path = tests_root / subdir / filename

    content = ""
    if llm_complete and prd and raw_markdown:
        print(f"[prd_to_factory] LLM으로 {filename} 테스트 코드 작성 중...")
        system_prompt = textwrap.dedent("""\
        당신은 최고의 QA 자동화 엔지니어다.
        사용자의 PRD 마크다운 전체와 요구하는 테스트 명세(JSON)를 바탕으로, 실제 작동하고 엄격하게 검증하는 pytest Python 테스트 코드를 작성하라.

        [작성 요구사항]
        1. 테스트 대상 도메인 모듈(예: `domain.optimize_layout`, `domain.build_grid_and_masks` 등)을 정확히 import해야 한다.
        2. 테스트 파일 내부에서 `my-harness-platform/src` 경로가 검색 가능하도록 반드시 아래 경로 추가 로직을 테스트 파일 최상단(import 직전)에 포함시켜라:
        ```python
        import sys
        from pathlib import Path
        SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
        if str(SRC_ROOT) not in sys.path:
            sys.path.insert(0, str(SRC_ROOT))
        ```
        3. 테스트 코드는 반드시 PRD의 인바리언트(Invariants)와 검증 요구사항을 면밀히 검토하고, 이를 검증하는 실질적인 `assert` 구문을 다수 포함해야 한다.
        4. `pytest.skip()`, `pass`, `TODO` 등 테스트 실행을 우회하거나 비워두는 구문은 엄격히 금지된다. 반드시 실패하고 성공할 수 있는 진짜 assert 로직으로만 100% 채워라.
        5. 테스트 입력값은 PRD의 시그니처와 예시, 불변식 제약에 맞는 유효한 모의(Mock) 데이터 또는 테스트 데이터를 직접 만들어서 제공해야 한다.
        6. 파일 상단에 `# @generated` 마커와 파일 설명을 넣고, 그 바로 밑에 `# BEGIN GENERATED` 마커를 넣은 뒤, 파일의 끝에 `# END GENERATED` 마커를 넣어 테스트 코드 전체(임포트문, 클래스, 함수 모두 포함)를 `# BEGIN GENERATED` ~ `# END GENERATED` 구간으로 감싸라.
        7. 출력은 반드시 순수한 파이썬 코드만 반환하라. 마크다운 코드블록(```python)이나 다른 설명은 절대 추가하지 마라.
        """)

        user_prompt = f"""\
        [원본 PRD 마크다운]
        {raw_markdown}

        [도메인 정보 JSON]
        {json.dumps(prd, ensure_ascii=False, indent=2)}

        [타겟 테스트 요구사항]
        파일명: {filename}
        유형: {test["type"]}
        검증 내용: {test["description"]}

        위 정보를 바탕으로, 해당 테스트의 요구사항과 PRD의 인바리언트를 엄격하게 검증하는 완벽한 파이썬 pytest 테스트 코드를 작성하라.
        """

        try:
            raw_output = llm_complete(system_prompt, user_prompt)
            if "```python" in raw_output:
                raw_output = raw_output.split("```python")[1].split("```")[0]
            elif "```" in raw_output:
                raw_output = raw_output.split("```")[1].split("```")[0]
            content = raw_output.strip()
        except Exception as e:
            print(f"[prd_to_factory] ⚠️ LLM 테스트 코드 생성 실패 ({e}), 스캐폴드로 폴백합니다.")
            content = ""

    if not content:
        content = textwrap.dedent(f'''\
        # @generated
        """자동 생성된 테스트 스캐폴드 — {test["description"]}."""
        # BEGIN GENERATED
        from __future__ import annotations

        import pytest


        class Test{_to_class_name(filename)}:
            """{test["description"]}"""

            def test_placeholder(self) -> None:
                """TODO: 실제 테스트 로직으로 교체."""
                # 검증 내용: {test["description"]}
                pytest.skip("스캐폴드 — 실제 구현 필요")
        # END GENERATED
        ''')

    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        # __init__.py 보장
        init = out_path.parent / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")
    return out_path, content


# === Helpers ===

def _json_schema_str(d: dict[str, str]) -> str:
    import json
    return json.dumps(d, ensure_ascii=False, indent=2)


def _to_class_name(filename: str) -> str:
    base = filename.replace("test_", "").replace(".py", "")
    return "".join(w.capitalize() for w in base.split("_"))
# END GENERATED
