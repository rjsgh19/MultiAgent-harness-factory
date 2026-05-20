# @generated
"""확장된 FailureType Enum 및 FailureRecord 정의.

State에는 traceback 본문을 절대 저장하지 않는다. 본 모듈의 FailureRecord는
오직 `trace_path` (storage/traces/ 내 파일 경로) 만을 참조한다.
"""
# BEGIN GENERATED
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class FailureType(str, Enum):
    """파이프라인이 인식하는 모든 실패 유형."""

    SYNTAX = "SYNTAX"
    IMPORT_ERROR = "IMPORT_ERROR"
    TYPE_ERROR = "TYPE_ERROR"
    TEST_ASSERTION = "TEST_ASSERTION"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    INFRA_TIMEOUT = "INFRA_TIMEOUT"
    SPEC_DRIFT = "SPEC_DRIFT"
    UNKNOWN = "UNKNOWN"

    # === Helpers ===

    @classmethod
    def hitl_triggers(cls) -> frozenset["FailureType"]:
        """이 유형들이 발생하면 즉시 HITL interrupt를 발동한다."""
        return frozenset({cls.SECURITY_VIOLATION, cls.INFRA_TIMEOUT, cls.SPEC_DRIFT})

    @classmethod
    def from_exception(cls, exc: BaseException) -> "FailureType":
        """예외 객체를 FailureType으로 매핑."""
        if isinstance(exc, SyntaxError):
            return cls.SYNTAX
        if isinstance(exc, ImportError):
            return cls.IMPORT_ERROR
        if isinstance(exc, TypeError):
            return cls.TYPE_ERROR
        if isinstance(exc, AssertionError):
            return cls.TEST_ASSERTION
        if isinstance(exc, TimeoutError):
            return cls.INFRA_TIMEOUT
        if isinstance(exc, PermissionError):
            return cls.SECURITY_VIOLATION
        if isinstance(exc, MemoryError):
            return cls.RESOURCE_LIMIT
        return cls.UNKNOWN


class FailureRecord(BaseModel):
    """State에 안전하게 보관되는 실패 메타데이터.

    *절대로* traceback 본문을 안에 담지 않는다. 대신 storage/traces/ 하위의
    파일 경로만 보관하여 State Explosion을 방어한다.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    failure_type: FailureType = Field(..., description="실패 유형 분류")
    summary: str = Field(..., max_length=240, description="한 줄 요약 (240자 제한)")
    trace_path: Optional[str] = Field(
        default=None,
        description="storage/traces/ 하위의 traceback 덤프 파일 상대 경로",
    )
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    node: str = Field(..., description="실패가 발생한 그래프 노드 이름")
    attempt: int = Field(default=1, ge=1, description="재시도 횟수 (1-based)")

    @field_validator("trace_path")
    @classmethod
    def _validate_trace_path(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        # 경로 traversal 방지: '..' 금지 + storage/traces/ 하위만 허용
        if ".." in v.replace("\\", "/").split("/"):
            raise ValueError("trace_path는 .. 컴포넌트를 포함할 수 없다")
        norm = v.replace("\\", "/")
        if not norm.startswith("storage/traces/"):
            raise ValueError("trace_path는 반드시 storage/traces/ 하위여야 한다")
        return norm

    @field_validator("summary")
    @classmethod
    def _no_multiline_summary(cls, v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("summary는 단일 줄이어야 한다 (멀티라인 traceback 누적 금지)")
        return v.strip()

    def is_hitl_trigger(self) -> bool:
        return self.failure_type in FailureType.hitl_triggers()


def trace_path_for(node: str, traces_root: Path) -> Path:
    """주어진 노드와 시각 기준 신규 traceback 파일 경로를 산출."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    return traces_root / f"{node}_{ts}.trace.log"
# END GENERATED
