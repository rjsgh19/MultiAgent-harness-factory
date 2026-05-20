# @generated
"""Spec ↔ Code AST 역검증 디텍터.

도메인 명세서(`domain_spec.yaml`)에 선언된 함수/클래스 시그니처가 실제로
생성된 코드(`my-harness-platform/src/...`)와 일치하는지 AST 추출로 역검증한다.

불일치 발견 시 `DriftReport`를 반환하고, 호출자는 `FailureType.SPEC_DRIFT`로
즉시 파이프라인 분기를 한다.
"""
# BEGIN GENERATED
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class DriftReport:
    """드리프트 검증 결과. drifted=True면 SPEC_DRIFT를 발동한다."""

    drifted: bool
    missing_contracts: list[str] = field(default_factory=list)
    signature_mismatches: list[str] = field(default_factory=list)
    forbidden_imports_used: list[str] = field(default_factory=list)
    invariant_violations: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not self.drifted:
            return "no-drift"
        parts: list[str] = []
        if self.missing_contracts:
            parts.append(f"missing={self.missing_contracts}")
        if self.signature_mismatches:
            parts.append(f"sig_mismatch={self.signature_mismatches}")
        if self.forbidden_imports_used:
            parts.append(f"forbidden_imports={self.forbidden_imports_used}")
        if self.invariant_violations:
            parts.append(f"invariants={self.invariant_violations}")
        return "; ".join(parts) or "drift"


class DriftDetector:
    """`domain_spec.yaml` 기준 AST 역검증."""

    def __init__(self, domain_spec_path: Path) -> None:
        if not domain_spec_path.exists():
            raise FileNotFoundError(f"domain spec 부재: {domain_spec_path}")
        self._spec: dict[str, Any] = yaml.safe_load(domain_spec_path.read_text(encoding="utf-8")) or {}
        self._project_root = domain_spec_path.resolve().parents[2]

    def verify(self, source_root: Optional[Path] = None) -> DriftReport:
        report = DriftReport(drifted=False)
        contracts: list[dict[str, Any]] = self._spec.get("contracts", [])
        forbidden: set[str] = set(self._spec.get("forbidden_imports", []))

        # 1) 모듈별 AST 인덱스 구축
        indexes: dict[str, _ModuleIndex] = {}
        for c in contracts:
            module_rel: str = c["module"]
            mod_index = indexes.get(module_rel)
            if mod_index is None:
                mod_index = self._index_module(module_rel, source_root)
                indexes[module_rel] = mod_index

            kind = c.get("kind", "function")
            name = c["name"]
            target = mod_index.functions.get(name) if kind == "function" else mod_index.classes.get(name)
            if target is None:
                report.missing_contracts.append(f"{module_rel}::{name}")
                continue
            if kind == "function":
                mismatch = self._check_function_signature(target, c)
                if mismatch:
                    report.signature_mismatches.append(f"{module_rel}::{name} — {mismatch}")
                if c.get("docstring_required") and not ast.get_docstring(target):
                    report.signature_mismatches.append(f"{module_rel}::{name} — docstring 누락")

        # 2) forbidden imports 위반 (모든 인덱싱된 모듈 대상)
        for mod_index in indexes.values():
            for imp in mod_index.imports:
                root = imp.split(".")[0]
                if root in forbidden:
                    report.forbidden_imports_used.append(f"{mod_index.module_path}::{imp}")

        # 3) invariants 추가 검증 (현 단계는 메타 검증만 — 실제 적용은 sandbox에서)
        for inv in self._spec.get("invariants", []):
            if "required_keys" in inv:
                # 도메인 spec dict 자체가 이 키를 포함해야 한다는 메타 검증
                missing = [k for k in inv["required_keys"] if k not in self._spec]
                if missing:
                    report.invariant_violations.append(f"{inv['id']}: missing keys {missing}")

        report.drifted = bool(
            report.missing_contracts
            or report.signature_mismatches
            or report.forbidden_imports_used
            or report.invariant_violations
        )
        return report

    # === Internal ===

    def _index_module(self, module_rel: str, source_root: Optional[Path]) -> "_ModuleIndex":
        root = source_root or self._project_root
        module_path = (root / module_rel).resolve()
        idx = _ModuleIndex(module_path=str(module_path).replace("\\", "/"))
        if not module_path.exists():
            return idx
        # 디렉토리면 안쪽 .py 전체를 합산 (단순 모듈 단위 검증 — 첫 시그니처 매칭).
        py_files = (
            sorted(module_path.rglob("*.py"))
            if module_path.is_dir()
            else [module_path]
        )
        for f in py_files:
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    idx.functions.setdefault(node.name, node)
                elif isinstance(node, ast.AsyncFunctionDef):
                    idx.functions.setdefault(node.name, node)
                elif isinstance(node, ast.ClassDef):
                    idx.classes.setdefault(node.name, node)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        idx.imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    idx.imports.add(node.module)
        return idx

    @staticmethod
    def _check_function_signature(node: ast.FunctionDef, contract: dict[str, Any]) -> Optional[str]:
        expected_params: list[dict[str, str]] = contract.get("parameters", []) or []
        actual_args = [a.arg for a in node.args.args]
        # self/cls 제외
        if actual_args and actual_args[0] in ("self", "cls"):
            actual_args = actual_args[1:]
        if len(actual_args) != len(expected_params):
            return f"arity {len(actual_args)} != expected {len(expected_params)}"
        for i, p in enumerate(expected_params):
            if actual_args[i] != p["name"]:
                return f"param[{i}] '{actual_args[i]}' != expected '{p['name']}'"
        return None


@dataclass
class _ModuleIndex:
    module_path: str
    functions: dict[str, ast.FunctionDef] = field(default_factory=dict)
    classes: dict[str, ast.ClassDef] = field(default_factory=dict)
    imports: set[str] = field(default_factory=set)
# END GENERATED
