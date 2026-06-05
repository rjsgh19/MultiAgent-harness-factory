# @generated
"""인간 수동 개입 인터럽트 제어.

조건 충족 시 LangGraph의 `interrupt()`를 호출하여 사람의 입력을 기다린다.
LangGraph가 미설치된 환경에서는 `HITLInterrupt` 예외를 발생시키는 폴백을 사용한다 —
절대로 사일런트하게 우회하지 않는다.
"""
# BEGIN GENERATED
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from harness_engine.services.telemetry import get_telemetry
from harness_engine.state.failure_types import FailureType
from harness_engine.state.persistent_state import PersistentState


class HITLInterrupt(RuntimeError):
    """LangGraph interrupt 미가용 시의 폴백 신호."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(payload.get("reason", "HITL required"))
        self.payload = payload


@dataclass
class HITLController:
    """interrupt() 발동 및 reason 페이로드 빌더."""

    enabled: bool = True

    def should_interrupt(self, persistent: PersistentState) -> bool:
        if not self.enabled:
            return False
        return persistent.should_interrupt()

    def trigger(self, persistent: PersistentState, trace_id: str, run_id: str) -> dict[str, Any]:
        last = persistent.failure_history[-1] if persistent.failure_history else None
        payload: dict[str, Any] = {
            "reason": "HITL required",
            "run_id": run_id,
            "trace_id": trace_id,
            "counters": persistent.counters.model_dump(),
            "last_failure": (last.model_dump() if last else None),
        }
        if last is not None:
            payload["trigger_failure_type"] = last.failure_type.value
        else:
            payload["trigger_failure_type"] = FailureType.UNKNOWN.value

        get_telemetry().warning(
            "hitl", trace_id, "HITL interrupt 발동",
            run_id=run_id,
            **{k: v for k, v in payload.items() if k not in ("reason", "run_id", "trace_id")},
        )
        try:
            from langgraph.types import interrupt  # type: ignore

            return interrupt(payload)
        except ImportError:
            # 폴백: LangGraph 미설치 환경
            raise HITLInterrupt(payload) from None
        except RuntimeError:
            # 폴백: LangGraph는 설치되어 있으나 그래프 컨텍스트 밖에서 실행 중
            # (예: python -m harness_engine.graph.workflow 독립 실행 모드)
            raise HITLInterrupt(payload) from None
# END GENERATED
