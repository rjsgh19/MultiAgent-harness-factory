# @generated
"""infrastructure.adapters — Claude / OpenAI / Aider 벤더 격리 진입점.

이 모듈 외부에서는 절대로 벤더 SDK를 import해서는 안 된다.
LLM 호출은 본 패키지의 `LLMAdapter` 프로토콜을 통해서만 이루어진다.
"""
# BEGIN GENERATED
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class LLMRequest:
    """벤더 비종속 LLM 호출 요청."""

    system_prompt: str
    user_prompt: str
    temperature: float = 0.0       # 결정성 강제 — 절대 수정 금지
    max_tokens: int = 4096
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    """벤더 비종속 LLM 호출 응답."""

    text: str
    model: str
    finish_reason: str
    usage: dict[str, int] = field(default_factory=dict)


class LLMAdapter(Protocol):
    """모든 벤더 어댑터가 만족해야 하는 프로토콜."""

    name: str

    def complete(self, request: LLMRequest) -> LLMResponse: ...


__all__ = ["LLMRequest", "LLMResponse", "LLMAdapter"]
# END GENERATED
