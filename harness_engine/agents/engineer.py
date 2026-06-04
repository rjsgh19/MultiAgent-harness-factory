# @generated
"""Engineer Agent — 최초 코드 생성 + 자가 치유 패치 수정 통합.

Planner의 계획(`plan`)을 받아 `# BEGIN GENERATED ~ # END GENERATED` 구간 본문만
산출한다. 산출물은 artifact_writer에 위임되며 본 에이전트는 직접 파일을 쓰지 않는다.
"""
# BEGIN GENERATED
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from harness_engine.services.prompt_loader import PromptContract
from harness_engine.services.replay_store import ReplayStore, ReplaySnapshot
from harness_engine.services.telemetry import get_telemetry


@dataclass
class EngineerAgent:
    contract: PromptContract
    llm_complete: Any  # callable(system, user) -> str
    replays: ReplayStore

    def synthesize(
        self,
        run_id: str,
        trace_id: str,
        plan: dict[str, Any],
        spec_paths: list[str],
        specs: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        telemetry = get_telemetry()
        telemetry.event("engineer", "enter", trace_id, run_id=run_id,
                        steps=len(plan.get("steps", [])))

        # === [전략 C] 스펙 다이렉트 주입 ===
        # Planner가 Plan에 사양을 구구절절 써줄 필요 없이, Engineer가 명세서를 직접 참조한다.
        spec_block = ""
        if specs:
            spec_block = (
                "# Domain Specifications (직접 참조)\n"
                f"{json.dumps(specs, ensure_ascii=False, indent=2)}\n\n"
            )

        user_prompt = (
            "# Plan\n"
            f"{json.dumps(plan, ensure_ascii=False, indent=2)}\n\n"
            "위 명세서와 계획에 따라 패치 본문을 JSON으로 산출하라."
        )
        raw = self.llm_complete(self.contract.render(), user_prompt, spec_block)
        payload = self._parse_patches(raw)

        self.replays.save(ReplaySnapshot(
            run_id=run_id, trace_id=trace_id, node="engineer",
            prompt=user_prompt, spec_paths=spec_paths, tool_output=payload,
        ))
        telemetry.event("engineer", "exit", trace_id, run_id=run_id,
                        patches=len(payload.get("patches", [])))
        return payload

    @staticmethod
    def _parse_patches(raw: str) -> dict[str, Any]:
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
            if not isinstance(data, dict) or "patches" not in data:
                raise ValueError("patches 키 누락")
            for p in data["patches"]:
                if not all(k in p for k in ("target_file", "body")):
                    raise ValueError("패치 필수 키 누락")
                p.setdefault("section_id", "default")
                p.setdefault("language", "python")
                p.setdefault("rationale", "")
                # 경로 traversal 차단
                tf = str(p["target_file"]).replace("\\", "/")
                if ".." in tf.split("/") or tf.startswith("/"):
                    raise ValueError(f"비정상 경로 차단: {tf}")
                p["target_file"] = tf
            return data
        except (ValueError, TypeError) as exc:
            return {"patches": [], "_error": f"engineer json parse failed: {exc}",
                    "_raw_excerpt": raw[:240]}
# END GENERATED
