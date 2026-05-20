# @generated
"""Reviewer Agent — Spec 준수 검사 + 코드 비판.

drift_detector와 sandbox_runner의 결과를 종합하여 최종 PASS/FAIL을 판정한다.
LLM은 텍스트 비판만 수행할 뿐, 자체적으로 코드를 수정하지 않는다.
"""
# BEGIN GENERATED
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from harness_engine.services.prompt_loader import PromptContract
from harness_engine.services.replay_store import ReplayStore, ReplaySnapshot
from harness_engine.services.telemetry import get_telemetry
from harness_engine.state.failure_types import FailureType


@dataclass
class ReviewerAgent:
    contract: PromptContract
    llm_complete: Any
    replays: ReplayStore

    def review(
        self,
        run_id: str,
        trace_id: str,
        drift_summary: str,
        sandbox_excerpt: str,
        sandbox_passed: bool,
        sandbox_failure_type: str | None,
        spec_paths: list[str],
    ) -> dict[str, Any]:
        telemetry = get_telemetry()
        telemetry.event("reviewer", "enter", trace_id, run_id=run_id,
                        drift=drift_summary, sandbox_passed=sandbox_passed)

        user_prompt = (
            "# Drift\n"
            f"{drift_summary}\n\n"
            "# Sandbox\n"
            f"passed={sandbox_passed} failure_type={sandbox_failure_type}\n"
            f"excerpt: {sandbox_excerpt}\n\n"
            "위 결과를 종합한 JSON 판정을 산출하라."
        )

        # LLM 비판 의견은 보조 정보로만 사용. 결정적 판정은 결정 규칙으로 처리.
        raw = self.llm_complete(self.contract.render(), user_prompt)
        opinion = self._safe_parse(raw)

        # === 결정 규칙 (LLM에 위임하지 않음) ===
        decided_failure: str
        if drift_summary != "no-drift":
            verdict = "FAIL"
            decided_failure = FailureType.SPEC_DRIFT.value
        elif not sandbox_passed:
            verdict = "FAIL"
            decided_failure = sandbox_failure_type or FailureType.UNKNOWN.value
        else:
            verdict = "PASS"
            decided_failure = "NONE"

        result = {
            "verdict": verdict,
            "failure_type": decided_failure,
            "issues": opinion.get("issues", []),
            "summary": opinion.get("summary", ""),
        }
        self.replays.save(ReplaySnapshot(
            run_id=run_id, trace_id=trace_id, node="reviewer",
            prompt=user_prompt, spec_paths=spec_paths, tool_output=result,
        ))
        telemetry.event("reviewer", "exit", trace_id, run_id=run_id,
                        verdict=verdict, failure_type=decided_failure)
        return result

    @staticmethod
    def _safe_parse(raw: str) -> dict[str, Any]:
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return {}
            return data
        except (ValueError, TypeError):
            return {}
# END GENERATED
