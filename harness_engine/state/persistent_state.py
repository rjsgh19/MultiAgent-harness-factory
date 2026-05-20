# @generated
"""영속성 체크포인트 상태 스키마.

PersistentState는 LangGraph checkpointer로 직렬화되는, 그래프 사이클을
건너뛰어도 보존되는 메타데이터다. 본문이 큰 페이로드는 절대로 담지 않으며,
오직 경로(traces, replays, telemetry)와 카운터, manifest 요약만 보관한다.

GraphState = TypedDict 형태로 LangGraph에 주입되는 최종 통합 상태.
"""
# BEGIN GENERATED
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from .ephemeral_state import EphemeralState
from .failure_types import FailureRecord


class AttemptCounters(BaseModel):
    """노드별 재시도 카운터 (3회 초과 시 HITL 트리거)."""

    model_config = {"extra": "forbid"}

    planner: int = 0
    engineer: int = 0
    reviewer: int = 0
    sandbox: int = 0
    total: int = 0
    max_repair_attempts: int = 3

    def bump(self, node: str) -> int:
        """해당 노드의 카운터를 1 증가시키고 신규 값을 반환."""
        current = getattr(self, node, None)
        if current is None:
            raise KeyError(f"알 수 없는 노드 카운터: {node}")
        new_val = int(current) + 1
        setattr(self, node, new_val)
        self.total += 1
        return new_val

    def exceeded(self) -> bool:
        # 지시서: "3회 이상 실패 시" → ≥ max_repair_attempts 즉시 HITL.
        return any(
            getattr(self, n) >= self.max_repair_attempts
            for n in ("planner", "engineer", "reviewer", "sandbox")
        )


class ManifestSummary(BaseModel):
    """`.generated_manifest.json` 의 경량 요약 (전체 엔트리 본문은 절대 미포함)."""

    model_config = {"extra": "forbid"}

    manifest_path: str = "my-harness-platform/.generated_manifest.json"
    entry_count: int = 0
    last_updated: Optional[datetime] = None


class PersistentState(BaseModel):
    """체크포인트와 매핑되는 영속 메타데이터."""

    model_config = {"extra": "forbid"}

    run_id: str = Field(..., description="이번 워크플로우 실행을 식별하는 UUID/ULID")
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    spec_paths: list[str] = Field(default_factory=list)
    counters: AttemptCounters = Field(default_factory=AttemptCounters)
    failure_history: list[FailureRecord] = Field(default_factory=list)
    manifest: ManifestSummary = Field(default_factory=ManifestSummary)

    # Pydantic v2: ClassVar 로 명시해야 모델 필드에서 제외된다.
    MAX_FAILURES: ClassVar[int] = 32

    def record_failure(self, failure: FailureRecord) -> None:
        self.failure_history.append(failure)
        # 폭주 방지: 최근 N개만 유지
        if len(self.failure_history) > self.MAX_FAILURES:
            self.failure_history = self.failure_history[-self.MAX_FAILURES :]

    def should_interrupt(self) -> bool:
        """HITL 트리거 조건: 임계 횟수 초과 또는 위험 실패 유형 발생."""
        if self.counters.exceeded():
            return True
        for f in reversed(self.failure_history[-5:]):
            if f.is_hitl_trigger():
                return True
        return False


class GraphState(TypedDict, total=False):
    """LangGraph 노드에 전달되는 최종 상태 컨테이너.

    중요: 이 안에 traceback/코드본문/AST덤프를 절대 넣지 마라.
    모든 무거운 페이로드는 storage/ 외부 파일에 격리하고 경로만 보관한다.
    """

    ephemeral: EphemeralState
    persistent: PersistentState
    plan: dict
    review: dict
    sandbox_result: dict
    drift_result: dict
    specs: dict[str, Any]
    patches: dict[str, Any]
    artifacts: list[dict[str, Any]]
    staging_dir: str
# END GENERATED
