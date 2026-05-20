# @generated
"""Aider 어댑터 — CLI/IPC 격리 구역.

본 어댑터는 외부 `aider` 패키지가 설치되어 있을 때만 동작하며,
부재 시 명확한 RuntimeError로 호출자를 차단한다.
"""
# BEGIN GENERATED
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from .. import LLMAdapter, LLMRequest, LLMResponse


@dataclass
class AiderAdapter(LLMAdapter):
    name: str = "aider"
    model: str = "default"

    def complete(self, request: LLMRequest) -> LLMResponse:
        if shutil.which("aider") is None:
            raise RuntimeError("aider CLI 미설치 — 어댑터 외부에서 호스트 폴백 금지")
        proc = subprocess.run(  # nosec - 격리 어댑터 내부, 입력은 신뢰된 source
            ["aider", "--quiet", "--message", request.user_prompt],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return LLMResponse(
            text=proc.stdout,
            model=self.model,
            finish_reason="stop" if proc.returncode == 0 else "error",
            usage={},
        )
# END GENERATED
