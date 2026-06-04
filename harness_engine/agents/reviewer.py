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

        # === [전략 A] 결정적 규칙 기반 조기 탈출 ===
        # FAIL이 확정된 경우 LLM 호출을 완전히 스킵하여 토큰 낭비를 차단한다.
        if drift_summary != "no-drift":
            result = {
                "verdict": "FAIL",
                "failure_type": FailureType.SPEC_DRIFT.value,
                "issues": [f"Spec drift detected: {drift_summary[:200]}"],
                "summary": "결정적 규칙 판정 - Spec drift로 즉시 FAIL (LLM 호출 생략)",
            }
            self.replays.save(ReplaySnapshot(
                run_id=run_id, trace_id=trace_id, node="reviewer",
                prompt="[SKIPPED — deterministic FAIL: spec drift]",
                spec_paths=spec_paths, tool_output=result,
            ))
            telemetry.event("reviewer", "early_exit", trace_id, run_id=run_id,
                            verdict="FAIL", failure_type=FailureType.SPEC_DRIFT.value,
                            reason="deterministic_drift")
            return result

        if not sandbox_passed:
            decided_failure = sandbox_failure_type or FailureType.UNKNOWN.value
            result = {
                "verdict": "FAIL",
                "failure_type": decided_failure,
                "issues": [f"Sandbox test failed: {sandbox_excerpt[:200]}"],
                "summary": "결정적 규칙 판정 - Sandbox 실패로 즉시 FAIL (LLM 호출 생략)",
            }
            self.replays.save(ReplaySnapshot(
                run_id=run_id, trace_id=trace_id, node="reviewer",
                prompt="[SKIPPED — deterministic FAIL: sandbox]",
                spec_paths=spec_paths, tool_output=result,
            ))
            telemetry.event("reviewer", "early_exit", trace_id, run_id=run_id,
                            verdict="FAIL", failure_type=decided_failure,
                            reason="deterministic_sandbox")
            return result

        # === PASS 경로 — 세부 품질 이슈 탐색을 위해 LLM 비판 수행 ===
        user_prompt = (
            "# Drift\n"
            f"{drift_summary}\n\n"
            "# Sandbox\n"
            f"passed={sandbox_passed} failure_type={sandbox_failure_type}\n"
            f"excerpt: {sandbox_excerpt}\n\n"
            "위 결과를 종합한 JSON 판정을 산출하라."
        )

        raw = self.llm_complete(self.contract.render(), user_prompt)
        opinion = self._safe_parse(raw)

        result = {
            "verdict": "PASS",
            "failure_type": "NONE",
            "issues": opinion.get("issues", []),
            "summary": opinion.get("summary", ""),
        }
        self.replays.save(ReplaySnapshot(
            run_id=run_id, trace_id=trace_id, node="reviewer",
            prompt=user_prompt, spec_paths=spec_paths, tool_output=result,
        ))
        telemetry.event("reviewer", "exit", trace_id, run_id=run_id,
                        verdict="PASS", failure_type="NONE")
        return result

    @staticmethod
    def _safe_parse(raw: str) -> dict[str, Any]:
        try:
            raw = raw.strip()
            if raw.startswith("```"):
                lines = raw.splitlines()
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                raw = "\n".join(lines).strip()

            data = json.loads(raw)
            if not isinstance(data, dict):
                return {}
            return data
        except (ValueError, TypeError):
            return {}
# END GENERATED
