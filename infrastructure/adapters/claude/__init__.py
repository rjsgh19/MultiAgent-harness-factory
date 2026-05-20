# @generated
"""Claude API 어댑터 격리 구역.

벤더 SDK(`anthropic`) 임포트는 본 모듈로만 한정한다. 부재 시 명확한
ImportError를 발생시키며, 절대로 호스트 폴백 LLM 호출을 시도하지 않는다.
"""
# BEGIN GENERATED
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .. import LLMAdapter, LLMRequest, LLMResponse


@dataclass
class ClaudeAdapter(LLMAdapter):
    name: str = "claude"
    model: str = "claude-opus-4-7"
    api_key_env: str = "ANTHROPIC_API_KEY"

    def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "anthropic SDK 미설치 — 어댑터 외부에서 호스트 폴백 금지"
            ) from exc

        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"환경변수 {self.api_key_env} 미설정")

        client = anthropic.Anthropic(api_key=api_key)
        result = client.messages.create(
            model=self.model,
            system=request.system_prompt,
            max_tokens=request.max_tokens,
            temperature=request.temperature,  # 반드시 0
            messages=[{"role": "user", "content": request.user_prompt}],
        )
        text = "".join(
            block.text for block in result.content if getattr(block, "type", None) == "text"
        )
        usage: dict[str, int] = {}
        if hasattr(result, "usage") and result.usage:
            usage = {
                "input_tokens": int(getattr(result.usage, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(result.usage, "output_tokens", 0) or 0),
            }
        return LLMResponse(
            text=text,
            model=self.model,
            finish_reason=getattr(result, "stop_reason", "stop") or "stop",
            usage=usage,
        )
# END GENERATED
