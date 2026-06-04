# @generated
"""Planner Agent — 기능 설계 + 실패 로그 진단/분석 통합.

주요 책임:
1. spec_loader가 적재한 YAML 명세서를 기반으로 변경 계획을 생성.
2. 직전 실패 레코드(`FailureRecord.trace_path`)가 있으면 파일을 열어 원인을 분류.
3. 출력은 항상 JSON. LLM 어댑터는 본 클래스 외부에서 주입(DI)된다.
"""
# BEGIN GENERATED
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from harness_engine.services.prompt_loader import PromptContract
from harness_engine.services.replay_store import ReplayStore, ReplaySnapshot
from harness_engine.services.telemetry import get_telemetry
from harness_engine.state.failure_types import FailureRecord, FailureType


@dataclass
class PlannerAgent:
    """planner.md 계약 기반 계획 수립기."""

    contract: PromptContract
    llm_complete: Any  # callable: (system, user) -> str  (어댑터 DI)
    replays: ReplayStore
    project_root: Path

    def plan(
        self,
        run_id: str,
        trace_id: str,
        spec_paths: list[str],
        specs: dict[str, dict[str, Any]],
        last_failure: Optional[FailureRecord] = None,
    ) -> dict[str, Any]:
        telemetry = get_telemetry()
        telemetry.event("planner", "enter", trace_id, run_id=run_id, specs=len(specs))

        failure_block = self._format_failure(last_failure)
        user_prompt, spec_block = self._compose_user_prompt(specs, failure_block)
        raw = self.llm_complete(self.contract.render(), user_prompt, spec_block)
        plan = self._parse_json(raw, fallback_diagnosis="initial-plan")

        self.replays.save(ReplaySnapshot(
            run_id=run_id, trace_id=trace_id, node="planner",
            prompt=user_prompt, spec_paths=spec_paths, tool_output=plan,
        ))
        telemetry.event("planner", "exit", trace_id, run_id=run_id,
                        steps=len(plan.get("steps", [])),
                        failure_class=plan.get("failure_class"))
        return plan

    # === Internal ===

    def _format_failure(self, failure: Optional[FailureRecord]) -> str:
        if failure is None:
            return "직전 실패 없음 (initial plan)."
        # State에서는 경로만 보관 — 본문은 여기서만 외부 파일을 열어 발췌한다.
        excerpt = ""
        if failure.trace_path:
            p = (self.project_root / failure.trace_path).resolve()
            if p.exists():
                raw = p.read_text(encoding="utf-8", errors="replace")
                # 최대 2KB만 발췌하여 LLM 입력 폭주 방지
                excerpt = raw[-2048:]
        return (
            f"직전 실패: type={failure.failure_type.value} attempt={failure.attempt}\n"
            f"요약: {failure.summary}\n"
            f"--- trace excerpt (최대 2KB) ---\n{excerpt}\n--- end ---"
        )

    def _compose_user_prompt(
        self, specs: dict[str, dict[str, Any]], failure_block: str
    ) -> tuple[str, str]:
        import os
        target_domain = os.environ.get("TARGET_DOMAIN", "harness_automation")
        
        # 스펙 인덱스 압축 — 타겟 도메인 스펙인 경우 contracts 계약 정보를 함께 제공
        spec_index = {}
        for name, s in specs.items():
            if target_domain in name or name == "domain_spec":
                spec_index[name] = {
                    "version": s.get("version"),
                    "top_keys": sorted(s.keys()),
                    "contracts": s.get("contracts", [])
                }
            else:
                spec_index[name] = {
                    "version": s.get("version"),
                    "top_keys": sorted(s.keys())
                }
                
        spec_block = (
            "# Specs Index\n"
            f"{json.dumps(spec_index, ensure_ascii=False, indent=2)}\n\n"
        )
        user_prompt = (
            "# Last Failure\n"
            f"{failure_block}\n\n"
            "위 정보를 토대로 JSON 계획을 산출하라."
        )
        return user_prompt, spec_block

    @staticmethod
    def _parse_json(raw: str, fallback_diagnosis: str) -> dict[str, Any]:
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
                raise ValueError("계획은 JSON object여야 함")
            data.setdefault("diagnosis", fallback_diagnosis)
            data.setdefault("failure_class", FailureType.UNKNOWN.value)
            data.setdefault("steps", [])
            data.setdefault("exit_criteria", "all tests pass + no drift")
            return data
        except (ValueError, TypeError) as exc:
            return {
                "diagnosis": f"planner json parse failed: {exc}",
                "failure_class": FailureType.UNKNOWN.value,
                "steps": [],
                "exit_criteria": "n/a",
                "_raw_excerpt": raw[:240],
            }
# END GENERATED
