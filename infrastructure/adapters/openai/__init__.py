# @generated
"""OpenAI API 어댑터 격리 구역 (벤더 SDK는 본 모듈 외부 import 금지)."""
# BEGIN GENERATED
from __future__ import annotations

import os
from dataclasses import dataclass

from .. import LLMAdapter, LLMRequest, LLMResponse


@dataclass
class OpenAIAdapter(LLMAdapter):
    name: str = "openai"
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"

    def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:
            raise RuntimeError("openai SDK 미설치 — 어댑터 외부 폴백 금지") from exc

        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"환경변수 {self.api_key_env} 미설정")
        client = OpenAI(api_key=api_key)
        rsp = client.chat.completions.create(
            model=self.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            messages=[
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
        )
        choice = rsp.choices[0]
        return LLMResponse(
            text=choice.message.content or "",
            model=self.model,
            finish_reason=choice.finish_reason or "stop",
            usage={
                "input_tokens": int(getattr(rsp.usage, "prompt_tokens", 0) or 0),
                "output_tokens": int(getattr(rsp.usage, "completion_tokens", 0) or 0),
            },
        )
# END GENERATED
