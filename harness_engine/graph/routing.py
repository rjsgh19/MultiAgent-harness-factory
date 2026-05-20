# @generated
"""LangGraph 조건부 분기 결정기.

Reviewer 판정 결과와 PersistentState의 카운터를 바탕으로 다음 노드를 결정한다.
- PASS  → END (artifact 드롭 완료)
- FAIL (재시도 여유 있음, HITL 트리거 아님) → planner (자가 치유 루프)
- FAIL (3회 초과 OR HITL 트리거 유형) → hitl (interrupt)
"""
# BEGIN GENERATED
from __future__ import annotations

from enum import Enum

from harness_engine.state.failure_types import FailureType
from harness_engine.state.persistent_state import PersistentState


class RoutingDecision(str, Enum):
    CONTINUE_TO_END = "end"
    REPAIR_VIA_PLANNER = "planner"
    ESCALATE_TO_HITL = "hitl"


def decide_after_review(
    verdict: str,
    failure_type: str,
    persistent: PersistentState,
) -> RoutingDecision:
    if verdict == "PASS":
        return RoutingDecision.CONTINUE_TO_END

    # HITL 즉시 트리거 유형
    try:
        ft = FailureType(failure_type)
    except ValueError:
        ft = FailureType.UNKNOWN
    if ft in FailureType.hitl_triggers():
        return RoutingDecision.ESCALATE_TO_HITL

    if persistent.counters.exceeded():
        return RoutingDecision.ESCALATE_TO_HITL

    return RoutingDecision.REPAIR_VIA_PLANNER


def decide_after_sandbox(
    sandbox_passed: bool,
    failure_type: str | None,
    persistent: PersistentState,
) -> RoutingDecision:
    """드리프트 검증을 통과한 코드의 샌드박스 결과에 대한 라우팅."""
    if sandbox_passed:
        return RoutingDecision.CONTINUE_TO_END
    try:
        ft = FailureType(failure_type) if failure_type else FailureType.UNKNOWN
    except ValueError:
        ft = FailureType.UNKNOWN
    if ft in FailureType.hitl_triggers() or persistent.counters.exceeded():
        return RoutingDecision.ESCALATE_TO_HITL
    return RoutingDecision.REPAIR_VIA_PLANNER
# END GENERATED
