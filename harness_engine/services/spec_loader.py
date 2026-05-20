# @generated
"""YAML 스펙 로더 + 기초 무결성 검증.

agent_runtime/specifications/*.yaml 의 도메인/API/아키텍처 정책 명세를 안전하게 적재한다.
"""
# BEGIN GENERATED
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class SpecValidationError(ValueError):
    """스펙이 필수 필드를 결여하거나 형식 위반 시 발생."""


class SpecLoader:
    """SpecLoaderPort 구현."""

    REQUIRED_TOP_KEYS = ("version",)

    def load(self, path: str | Path) -> dict[str, Any]:
        p = Path(path)
        if not p.exists():
            raise SpecValidationError(f"spec 파일 부재: {p}")
        if p.suffix.lower() not in (".yaml", ".yml"):
            raise SpecValidationError(f"지원하지 않는 spec 확장자: {p.suffix}")
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise SpecValidationError(f"YAML 파싱 실패: {p} — {exc}") from exc

        if not isinstance(data, dict):
            raise SpecValidationError(f"spec 최상위는 mapping이어야 함: {p}")

        self.validate(data)
        return data

    def validate(self, data: dict[str, Any]) -> bool:
        for key in self.REQUIRED_TOP_KEYS:
            if key not in data:
                raise SpecValidationError(f"필수 키 누락: {key}")
        return True

    def load_many(self, root: str | Path) -> dict[str, dict[str, Any]]:
        root_p = Path(root)
        if not root_p.is_dir():
            raise SpecValidationError(f"spec 디렉토리 부재: {root_p}")
        out: dict[str, dict[str, Any]] = {}
        for f in sorted(root_p.glob("*.y*ml")):
            out[f.stem] = self.load(f)
        return out
# END GENERATED
