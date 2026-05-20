# @generated
"""마크다운 가이드 안전 파서 + Pydantic 계약 검증.

지정된 Allowlist 섹션만 발췌하여 LLM 호출 입력으로 변환한다.
가이드가 오염/위변조되었거나 Allowlist 외 섹션을 임의 주입하려 한 경우 즉시 차단한다.
"""
# BEGIN GENERATED
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# Allowlist: 본 헤더들만 LLM 입력으로 통과시킨다.
ALLOWED_SECTIONS: tuple[str, ...] = ("ROLE", "CONSTRAINTS", "OUTPUT_FORMAT")

# 섹션 헤더 패턴 — 정확히 `## SECTION_NAME` 형식만 허용.
_SECTION_HEADER = re.compile(r"^##[ \t]+([A-Z][A-Z0-9_]*)\s*$", re.MULTILINE)

# 위험 패턴: 프롬프트 인젝션 시도를 차단할 휴리스틱.
_INJECTION_SIGNATURES = (
    re.compile(r"```(?:sh|bash|powershell|cmd)", re.IGNORECASE),
    re.compile(r"ignore (all|previous|above) (instructions|rules|prompts)", re.IGNORECASE),
    re.compile(r"\bsystem\s*:\s*you are now", re.IGNORECASE),
    re.compile(r"<\s*script[^>]*>", re.IGNORECASE),
    # Trojan Source — Unicode bidi override 공격 (CVE-2021-42574 계열).
    re.compile(r"[‪-‮⁦-⁩]"),
    # ANSI escape 시퀀스 — 터미널 위변조 / 출력 가로채기.
    re.compile(r"\x1b\["),
    # Zero-width / invisible 문자 — 시각적 위변조.
    re.compile(r"[​-‏﻿]"),
)

_MAX_BYTES = 64 * 1024  # 가이드 파일 64KB 상한 — 비정상 거대 파일 차단


class PromptContractError(ValueError):
    """프롬프트 계약 위반 — 즉시 실행 차단."""


class PromptContract(BaseModel):
    """파싱된 가이드의 안전 계약 표현."""

    model_config = {"frozen": True, "extra": "forbid"}

    role: str = Field(..., min_length=1, max_length=4000)
    constraints: str = Field(..., min_length=1, max_length=6000)
    output_format: str = Field(..., min_length=1, max_length=4000)
    source_path: str
    sha256: str = Field(..., min_length=64, max_length=64)

    @field_validator("role", "constraints", "output_format")
    @classmethod
    def _strip_dangerous(cls, v: str) -> str:
        for pat in _INJECTION_SIGNATURES:
            if pat.search(v):
                raise PromptContractError(
                    f"가이드에 위험 패턴 감지: {pat.pattern!r}"
                )
        return v.strip()

    def render(self) -> str:
        """LLM에 주입할 최종 안전 문자열을 합성."""
        return (
            "## ROLE\n"
            f"{self.role}\n\n"
            "## CONSTRAINTS\n"
            f"{self.constraints}\n\n"
            "## OUTPUT_FORMAT\n"
            f"{self.output_format}\n"
        )


class PromptLoader:
    """`docs/agent_guides/*.md` 안전 파서."""

    def __init__(self, allowed_sections: tuple[str, ...] = ALLOWED_SECTIONS) -> None:
        self._allowed = tuple(s.upper() for s in allowed_sections)

    def load(self, path: Path) -> PromptContract:
        if not path.exists():
            raise PromptContractError(f"가이드 파일 부재: {path}")
        size = path.stat().st_size
        if size > _MAX_BYTES:
            raise PromptContractError(
                f"가이드 파일이 비정상적으로 큼 ({size} bytes > {_MAX_BYTES}) — 위변조 의심"
            )
        raw = path.read_text(encoding="utf-8")
        sections = self._parse_sections(raw)

        # Allowlist 외 섹션 검출 → 거부
        unexpected = set(sections) - set(self._allowed)
        # 자유 헤더(예: 제목 `# Planner Agent Guide`) 는 sections에 포함되지 않으므로 무시.
        if unexpected:
            raise PromptContractError(f"허용 외 섹션 발견: {sorted(unexpected)}")

        # 필수 섹션 누락 검출
        missing = [s for s in self._allowed if s not in sections]
        if missing:
            raise PromptContractError(f"필수 섹션 누락: {missing}")

        import hashlib

        sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return PromptContract(
            role=sections["ROLE"],
            constraints=sections["CONSTRAINTS"],
            output_format=sections["OUTPUT_FORMAT"],
            source_path=str(path).replace("\\", "/"),
            sha256=sha,
        )

    # === Internal ===

    def _parse_sections(self, markdown: str) -> dict[str, str]:
        """`## NAME` 헤더를 기준으로 본문을 잘라 dict 반환."""
        matches = list(_SECTION_HEADER.finditer(markdown))
        out: dict[str, str] = {}
        for i, m in enumerate(matches):
            name = m.group(1).upper()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
            body = markdown[start:end].strip()
            if name in out:
                raise PromptContractError(f"중복 섹션: {name}")
            out[name] = body
        return out

    # 호환용 메서드 — get
    def section(self, contract: PromptContract, name: str) -> Optional[str]:
        return {
            "ROLE": contract.role,
            "CONSTRAINTS": contract.constraints,
            "OUTPUT_FORMAT": contract.output_format,
        }.get(name.upper())
# END GENERATED
