# @generated
"""허용 import 통제 엔진.

`architecture_policy.yaml`의 의존성 방향 규칙을 코드로 인코딩하여,
artifact_writer가 파일 저장 직전에 위반 여부를 검사한다.
"""
# BEGIN GENERATED
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


@dataclass(frozen=True)
class ImportViolation:
    file: str
    imported: str
    reason: str


class ImportPolicy:
    """architecture_policy.yaml + domain_spec.yaml 기반 import 검사기."""

    def __init__(self, policy_path: Path, domain_spec_path: Path | None = None) -> None:
        self._policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        self._layers = {layer["name"]: layer for layer in self._policy.get("layers", [])}
        self._isolation = self._policy.get("isolation_rules", [])
        self._domain_forbidden: set[str] = set()
        if domain_spec_path and domain_spec_path.exists():
            domain_spec = yaml.safe_load(domain_spec_path.read_text(encoding="utf-8"))
            self._domain_forbidden = set(domain_spec.get("forbidden_imports", []))

    def check_file(self, file_path: Path) -> list[ImportViolation]:
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            return [ImportViolation(str(file_path), "<syntax>", f"parse error: {exc.msg}")]

        violations: list[ImportViolation] = []
        imports = list(self._collect_imports(tree))
        rel_str = str(file_path).replace("\\", "/")

        # 1) 도메인 레이어 forbidden import 검사
        if "/src/domain" in rel_str:
            for imp in imports:
                root = imp.split(".")[0]
                if root in self._domain_forbidden:
                    violations.append(
                        ImportViolation(rel_str, imp, "domain layer must remain dependency-free")
                    )

        # 2) 격리 규칙 (harness_engine/agents, harness_engine/graph 내부에서 벤더 SDK 금지)
        for rule in self._isolation:
            forbidden_in: list[str] = rule.get("forbidden_imports_in", [])
            forbidden_mods: list[str] = rule.get("forbidden_modules", [])
            if any(scope in rel_str for scope in forbidden_in):
                for imp in imports:
                    root = imp.split(".")[0]
                    if root in forbidden_mods:
                        violations.append(
                            ImportViolation(rel_str, imp, f"violates {rule['rule']}")
                        )

        # 3) 클린 아키텍처 의존성 방향
        owning_layer = self._owning_layer(rel_str)
        if owning_layer is not None:
            allowed = set(self._layers[owning_layer].get("may_import", []))
            for imp in imports:
                target_layer = self._layer_of_import(imp)
                if target_layer is None or target_layer == owning_layer:
                    continue
                if target_layer not in allowed:
                    violations.append(
                        ImportViolation(
                            rel_str,
                            imp,
                            f"layer '{owning_layer}' must not import '{target_layer}'",
                        )
                    )
        return violations

    @staticmethod
    def _collect_imports(tree: ast.AST) -> Iterable[str]:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                yield node.module

    def _owning_layer(self, rel_path: str) -> str | None:
        for name, layer in self._layers.items():
            if layer.get("path") and layer["path"] in rel_path:
                return name
        return None

    def _layer_of_import(self, module: str) -> str | None:
        # src.domain.foo / src.use_cases.bar 형식 추정
        parts = module.split(".")
        for name in self._layers:
            if name in parts:
                return name
        return None
# END GENERATED
