# @generated
"""휘발성 노드 상태 스키마.

EphemeralState는 한 그래프 사이클 안에서만 존재하며, 다음과 같은 정보를 보유한다:
- 직전 노드 산출물의 경량 메타 (코드 본문 전체는 금지 — 경로만)
- 노드별 breadcrumb (Trace ID와 시각)
- 직전 실패 레코드 (있을 때만)

코드 본문/AST 본문/traceback 본문 같은 무거운 페이로드는 절대로 담지 않는다.
"""
# BEGIN GENERATED
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .failure_types import FailureRecord


_MAX_BREADCRUMBS = 64
_MAX_SUMMARY_LEN = 240


class NodeBreadcrumb(BaseModel):
    """노드 단위 실행 흔적 — Trace ID, 진입/이탈 시각, 한 줄 요약."""

    model_config = {"frozen": True, "extra": "forbid"}

    node: str
    trace_id: str
    entered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    exited_at: Optional[datetime] = None
    summary: str = Field(default="", max_length=_MAX_SUMMARY_LEN)

    @field_validator("summary")
    @classmethod
    def _single_line(cls, v: str) -> str:
        if "\n" in v:
            raise ValueError("breadcrumb summary는 단일 줄이어야 한다")
        return v


class EphemeralState(BaseModel):
    """그래프 1회 실행 동안만 유지되는 휘발성 상태."""

    model_config = {"extra": "forbid"}

    trace_id: str = Field(..., description="이번 실행 전체를 식별하는 가상 Trace ID")
    breadcrumbs: list[NodeBreadcrumb] = Field(default_factory=list)
    last_artifact_path: Optional[str] = Field(
        default=None, description="가장 최근에 생성/패치된 산출물의 상대 경로",
    )
    last_spec_path: Optional[str] = Field(default=None)
    last_replay_path: Optional[str] = Field(default=None)
    last_failure: Optional[FailureRecord] = None
    awaiting_hitl: bool = False

    def push(self, crumb: NodeBreadcrumb) -> None:
        """breadcrumb를 추가하되 무한 누적을 방지한다."""
        self.breadcrumbs.append(crumb)
        if len(self.breadcrumbs) > _MAX_BREADCRUMBS:
            # 가장 오래된 절반을 잘라낸다 (FIFO 방식 압축).
            half = _MAX_BREADCRUMBS // 2
            self.breadcrumbs = self.breadcrumbs[-half:]

    def clear_failure(self) -> None:
        self.last_failure = None
        self.awaiting_hitl = False
# END GENERATED
