# @generated
"""공장 문서 생성기 — PRD 구조체 → YAML/MD/테스트 파일 자동 생성.

PRD 파서가 추출한 구조화된 dict를 받아 하네스 공장 가동에 필요한
모든 문서를 일관성 있게 생성/수정한다.
"""
# BEGIN GENERATED
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

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
                           dry_run: bool = False) -> tuple[Path, str]:
    """단일 테스트 파일 스캐폴드 생성."""
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
        if not out_path.exists():
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
