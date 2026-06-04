# @generated
"""하이브리드(Hybrid) 라우팅 어댑터.

역할(Role)에 따라 저렴한 모델과 똑똑한 모델로 트래픽을 분산시킨다.
"""
# BEGIN GENERATED
from __future__ import annotations

from dataclasses import dataclass

from .. import LLMAdapter, LLMRequest, LLMResponse


@dataclass
class HybridAdapter(LLMAdapter):
    name: str = "hybrid"
    cheap_adapter: LLMAdapter = None  # type: ignore
    smart_adapter: LLMAdapter = None  # type: ignore

    def complete(self, request: LLMRequest) -> LLMResponse:
        # 시스템 프롬프트(가이드) 내용에 기반하여 에이전트를 식별한다.
        # Engineer Agent는 고도의 코딩 능력이 필요하므로 smart_adapter로 라우팅한다.
        if "Engineer Agent Guide" in request.system_prompt:
            return self.smart_adapter.complete(request)
        
        # Planner, Reviewer 등은 cheap_adapter로 라우팅한다.
        return self.cheap_adapter.complete(request)
# END GENERATED
