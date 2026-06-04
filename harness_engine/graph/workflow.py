# @generated
"""LangGraph 상태 머신 빌드 스크립트.

원자적 파이프라인:
  load_spec → plan → engineer →
  drift_detector → (drift?yes→planner / no→sandbox) →
  sandbox_runner → reviewer → routing →
    PASS → artifact_writer → END
    FAIL → (planner | HITL)

3회 초과 OR SECURITY_VIOLATION / INFRA_TIMEOUT / SPEC_DRIFT → HITL interrupt.
"""
# BEGIN GENERATED
from __future__ import annotations

import sys
try:
    import dotenv
    import openai
    import anthropic
    import langgraph
    import docker
except ImportError as e:
    print(f"\n⚠️ 필수 라이브러리({e.name})가 설치되지 않았습니다.", file=sys.stderr)
    print("터미널에서 다음 명령어를 실행하여 의존성을 설치해주세요:", file=sys.stderr)
    print("    pip install -e .\n", file=sys.stderr)
    sys.exit(1)

import json
import os
import shutil
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from harness_engine.agents import EngineerAgent, PlannerAgent, ReviewerAgent
from harness_engine.graph.hitl import HITLController, HITLInterrupt
from harness_engine.graph.routing import RoutingDecision, decide_after_review
from harness_engine.services import (
    ArtifactWriter,
    DriftDetector,
    PromptLoader,
    ReplayStore,
    SandboxConfig,
    SandboxRunner,
    SpecLoader,
)
from harness_engine.services.artifact_writer import PathTraversalError
from harness_engine.services.telemetry import get_telemetry
from harness_engine.state import (
    EphemeralState,
    FailureRecord,
    FailureType,
    GraphState,
    NodeBreadcrumb,
    PersistentState,
)
from harness_engine.state.failure_types import trace_path_for


# 디터미니스틱 강제 — temperature는 항상 0.
LLM_TEMPERATURE = 0.0


# === LLM Adapter DI ===

def _stub_llm(system: str, user: str) -> str:
    """어댑터가 주입되지 않은 환경의 결정적 stub.

    실 운영 시 `FactoryWorkflow(llm_adapter=...)`로 ClaudeAdapter/OpenAIAdapter 주입.
    stub은 빈 계획/패치를 반환하여 파이프라인 형상을 검증할 수 있게 한다.
    """
    if "Plan" in user and "patches" not in user.lower():
        return json.dumps({"patches": []})
    if "## ROLE" in system and "Engineer" in system:
        return json.dumps({"patches": []})
    if "Drift" in user and "Sandbox" in user:
        return json.dumps({"verdict": "PASS", "failure_type": "NONE", "issues": [], "summary": "stub"})
    return json.dumps({
        "diagnosis": "stub",
        "failure_class": "UNKNOWN",
        "steps": [],
        "exit_criteria": "n/a",
    })


@dataclass
class FactoryWorkflow:
    """LangGraph StateGraph 빌더 + 폴백 순차 실행기.

    LangGraph가 설치되어 있으면 `as_graph()`로 컴파일된 상태 머신을 노출하고,
    설치되지 않은 환경에서는 `run_once()` 순차 실행기로 동일 파이프라인을 수행한다.
    """

    project_root: Path
    llm_adapter: Optional[Any] = None  # LLMAdapter (infrastructure.adapters.LLMAdapter)
    guides_dir: Path = field(init=False)
    specs_dir: Path = field(init=False)
    domain_spec_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.guides_dir = self.project_root / "docs" / "agent_guides"
        self.specs_dir = self.project_root / "agent_runtime" / "specifications"
        
        import os
        target_domain = os.environ.get("TARGET_DOMAIN")
        if target_domain:
            self.domain_spec_path = self.specs_dir / f"{target_domain}_domain_spec.yaml"
        else:
            self.domain_spec_path = self.specs_dir / "domain_spec.yaml"

        # 의존성 인스턴스화
        self.spec_loader = SpecLoader()
        self.prompt_loader = PromptLoader()
        self.replays = ReplayStore()
        self.drift = DriftDetector(self.domain_spec_path)
        self.sandbox = SandboxRunner(SandboxConfig())
        self.artifacts = ArtifactWriter(self.project_root)
        self.hitl = HITLController(enabled=os.environ.get("HITL_ENABLED", "true").lower() == "true")
        self.telemetry = get_telemetry()

        # 가이드 마크다운 → PromptContract (실시간 open/read + 계약 검증)
        self.planner_contract = self.prompt_loader.load(self.guides_dir / "planner.md")
        self.engineer_contract = self.prompt_loader.load(self.guides_dir / "engineer.md")
        self.reviewer_contract = self.prompt_loader.load(self.guides_dir / "reviewer.md")

        llm_complete = self._bind_llm()
        self.planner = PlannerAgent(
            contract=self.planner_contract, llm_complete=llm_complete,
            replays=self.replays, project_root=self.project_root,
        )
        self.engineer = EngineerAgent(
            contract=self.engineer_contract, llm_complete=llm_complete, replays=self.replays,
        )
        self.reviewer = ReviewerAgent(
            contract=self.reviewer_contract, llm_complete=llm_complete, replays=self.replays,
        )

    # === LangGraph Compile ===

    def as_graph(self):  # type: ignore[no-untyped-def]
        """LangGraph StateGraph 컴파일 결과 반환."""
        from langgraph.graph import StateGraph, END  # type: ignore

        g: Any = StateGraph(GraphState)  # type: ignore
        g.add_node("load_spec", self._n_load_spec)
        g.add_node("planner", self._n_planner)
        g.add_node("engineer", self._n_engineer)
        g.add_node("drift", self._n_drift)
        g.add_node("sandbox", self._n_sandbox)
        g.add_node("reviewer", self._n_reviewer)
        g.add_node("artifact", self._n_artifact)
        g.add_node("hitl", self._n_hitl)

        g.set_entry_point("load_spec")
        g.add_edge("load_spec", "planner")
        g.add_edge("planner", "engineer")
        g.add_edge("engineer", "drift")

        def _after_drift(state: GraphState) -> str:
            drift = state.get("drift_result", {})
            return "planner" if drift.get("drifted") else "sandbox"

        g.add_conditional_edges("drift", _after_drift, {"planner": "planner", "sandbox": "sandbox"})
        g.add_edge("sandbox", "reviewer")

        def _after_reviewer(state: GraphState) -> str:
            review = state.get("review", {})
            persistent: PersistentState = state["persistent"]
            decision = decide_after_review(
                review.get("verdict", "FAIL"),
                review.get("failure_type", "UNKNOWN"),
                persistent,
            )
            return {
                RoutingDecision.CONTINUE_TO_END: "artifact",
                RoutingDecision.REPAIR_VIA_PLANNER: "planner",
                RoutingDecision.ESCALATE_TO_HITL: "hitl",
            }[decision]

        g.add_conditional_edges(
            "reviewer", _after_reviewer,
            {"artifact": "artifact", "planner": "planner", "hitl": "hitl"},
        )
        g.add_edge("artifact", END)
        g.add_edge("hitl", END)
        return g.compile()

    # === Fallback 순차 실행기 (LangGraph 미가용 시) ===

    def run_once(self, max_iterations: int = 6) -> dict[str, Any]:
        state: GraphState = self._initial_state()
        # 노드 시퀀스를 직접 운전 — conditional edges 의미를 그대로 재현한다.
        for iteration in range(max_iterations):
            self.telemetry.event("workflow", "iter_start", state["ephemeral"].trace_id,
                                 run_id=state["persistent"].run_id, iter=iteration)
            try:
                state = self._n_load_spec(state) if iteration == 0 else state
                state = self._n_planner(state)
                state = self._n_engineer(state)
                state = self._n_drift(state)
                if state.get("drift_result", {}).get("drifted"):
                    # PathTraversal 분기는 SECURITY_VIOLATION으로 이미 기록됨 — 그 외는 SPEC_DRIFT.
                    eph = state["ephemeral"]
                    if not eph.last_failure or eph.last_failure.failure_type != FailureType.SECURITY_VIOLATION:
                        self._record_failure(state, FailureType.SPEC_DRIFT,
                                             state["drift_result"].get("summary", "drift")[:240],
                                             node="drift")
                    # staging 폐기 (재시도 시 신규 staging으로 재시작).
                    self._cleanup_staging(state)
                    # sequential run(run_once) 중 첫 이터레이션(코드가 아직 전혀 없는 상태)에서의 SPEC_DRIFT는
                    # 에이전트가 에러 로그를 보고 자가 치유할 수 있도록 HITL을 한 번 유예합니다.
                    if iteration == 0 and state.get("drift_result", {}).get("drifted"):
                        continue
                    if self.hitl.should_interrupt(state["persistent"]):
                        return self._do_hitl(state)
                    continue
                state = self._n_sandbox(state)
                state = self._n_reviewer(state)
                review = state.get("review", {})
                decision = decide_after_review(
                    review.get("verdict", "FAIL"),
                    review.get("failure_type", "UNKNOWN"),
                    state["persistent"],
                )
                if decision == RoutingDecision.CONTINUE_TO_END:
                    state = self._n_artifact(state)
                    return self._finalize(state, status="PASS")
                if decision == RoutingDecision.ESCALATE_TO_HITL:
                    return self._do_hitl(state)
                # 그 외 → planner로 복귀 (다음 iteration)
            except HITLInterrupt:
                raise
            except Exception as exc:  # noqa: BLE001
                self._record_exception(state, exc, node="workflow")
                if self.hitl.should_interrupt(state["persistent"]):
                    return self._do_hitl(state)
        # max iterations 도달 — HITL
        return self._do_hitl(state)

    # === Nodes ===

    def _n_load_spec(self, state: GraphState) -> GraphState:
        eph = state["ephemeral"]
        per = state["persistent"]
        crumb = NodeBreadcrumb(node="load_spec", trace_id=eph.trace_id, summary="loading specs")
        eph.push(crumb)
        specs = self.spec_loader.load_many(self.specs_dir)
        per.spec_paths = sorted(str((self.specs_dir / f"{name}.yaml").relative_to(self.project_root))
                                for name in specs.keys())
        eph.last_spec_path = per.spec_paths[0] if per.spec_paths else None
        state["specs"] = specs  # type: ignore[typeddict-unknown-key]
        self.telemetry.event("load_spec", "ok", eph.trace_id, run_id=per.run_id,
                             count=len(specs))
        return state

    def _n_planner(self, state: GraphState) -> GraphState:
        eph, per = state["ephemeral"], state["persistent"]
        per.counters.bump("planner")
        crumb = NodeBreadcrumb(node="planner", trace_id=eph.trace_id, summary="planning")
        eph.push(crumb)
        specs: dict[str, Any] = state.get("specs", {})  # type: ignore[typeddict-item]
        plan = self.planner.plan(
            run_id=per.run_id, trace_id=eph.trace_id,
            spec_paths=per.spec_paths, specs=specs,
            last_failure=eph.last_failure,
        )
        state["plan"] = plan
        return state

    def _n_engineer(self, state: GraphState) -> GraphState:
        eph, per = state["ephemeral"], state["persistent"]
        per.counters.bump("engineer")
        crumb = NodeBreadcrumb(node="engineer", trace_id=eph.trace_id, summary="synthesizing")
        eph.push(crumb)
        payload = self.engineer.synthesize(
            run_id=per.run_id, trace_id=eph.trace_id,
            plan=state.get("plan", {}), spec_paths=per.spec_paths,
            specs=state.get("specs"),  # [전략 C] 스펙 다이렉트 주입
        )
        # 패치 이력을 누적 병합하여 이전 자가 치유 코드 유실 방지
        existing_payload = state.get("patches") or {}
        existing_patches = existing_payload.get("patches", [])
        new_patches = payload.get("patches", [])
        
        merged = {p["target_file"]: p for p in existing_patches + new_patches}
        payload["patches"] = list(merged.values())
        
        state["patches"] = payload  # type: ignore[typeddict-unknown-key]
        return state

    def _n_drift(self, state: GraphState) -> GraphState:
        """Engineer 패치를 staging dir에 dry-apply한 뒤 drift_detector를 그 트리에 적용.

        명세서: [코드 생성 ➡️ drift_detector ➡️ sandbox ➡️ 통과 시에만 artifact_writer]
        실 디스크는 절대 건드리지 않는다.
        """
        eph = state["ephemeral"]
        crumb = NodeBreadcrumb(node="drift", trace_id=eph.trace_id, summary="drift check (staged)")
        eph.push(crumb)

        # 1) staging dir 준비 — 기존 my-harness-platform/src 트리를 카피.
        staging = self._prepare_staging(state)
        patches = state.get("patches", {}).get("patches", [])  # type: ignore[typeddict-item]

        # 2) 패치를 staging dir에 dry-apply (실 디스크 외부).
        try:
            self._apply_patches_to_staging(patches, staging)
        except PathTraversalError as exc:
            self._record_failure(state, FailureType.SECURITY_VIOLATION,
                                 f"path traversal: {exc}"[:240], node="drift")
            state["drift_result"] = {"drifted": True, "summary": f"path-traversal: {exc}"}
            return state

        # 3) 그 staging 트리를 기준으로 drift verify.
        report = self.drift.verify(source_root=staging)
        state["drift_result"] = {
            "drifted": report.drifted,
            "summary": report.summary(),
            "missing_contracts": report.missing_contracts,
            "signature_mismatches": report.signature_mismatches,
            "forbidden_imports_used": report.forbidden_imports_used,
            "staging_dir": str(staging),
        }
        state["staging_dir"] = str(staging)  # type: ignore[typeddict-unknown-key]
        self.telemetry.event("drift", "ok", eph.trace_id, drifted=report.drifted,
                             summary=report.summary(), staging=str(staging))
        return state

    # === Staging helpers ===

    def _prepare_staging(self, state: GraphState) -> Path:
        """이번 사이클 전용 임시 staging dir를 만든다. 동일 run 내에서는 재사용."""
        existing = state.get("staging_dir")  # type: ignore[typeddict-item]
        if existing and Path(existing).exists():
            return Path(existing)
        tmp_root = Path(tempfile.mkdtemp(prefix="harness_staging_"))
        src_root = self.project_root / "my-harness-platform"
        # src 트리 전체를 카피 (없을 수도 있음 — 그땐 빈 staging).
        if src_root.exists():
            shutil.copytree(src_root, tmp_root / "my-harness-platform", dirs_exist_ok=True)
        return tmp_root

    def _apply_patches_to_staging(self, patches: list[dict[str, Any]], staging: Path) -> None:
        """staging dir 내부에 patches를 dry-apply. PathTraversal은 차단한다."""
        from harness_engine.services.artifact_writer import ArtifactWriter

        staging_writer = ArtifactWriter(project_root=staging)
        for patch in patches:
            target_rel = str(patch["target_file"]).replace("\\", "/")
            # 절대 경로 + .. 컴포넌트 차단 (이미 engineer agent에서 1차 차단되지만 이중 방어).
            if target_rel.startswith("/") or ".." in target_rel.split("/"):
                raise PathTraversalError(f"비정상 target_file: {target_rel}")
            staging_writer.write_section(
                Path(target_rel), patch["body"], patch.get("section_id", "default"),
            )

    def _n_sandbox(self, state: GraphState) -> GraphState:
        eph, per = state["ephemeral"], state["persistent"]
        per.counters.bump("sandbox")
        crumb = NodeBreadcrumb(node="sandbox", trace_id=eph.trace_id, summary="testing (staged)")
        eph.push(crumb)
        # staging 트리의 tests를 채점한다 (실 디스크 절대 미사용).
        staging = state.get("staging_dir")  # type: ignore[typeddict-item]
        tests_target = (
            str(Path(staging) / "my-harness-platform" / "tests")
            if staging
            else "my-harness-platform/tests"
        )
        result = self.sandbox.run_tests(target=tests_target, trace_id=eph.trace_id)
        state["sandbox_result"] = {
            "passed": result.passed,
            "exit_code": result.exit_code,
            "duration_seconds": result.duration_seconds,
            "failure_type": result.failure_type.value if result.failure_type else None,
            "trace_path": result.trace_path,
            "stdout_excerpt": result.stdout_excerpt,
        }
        return state

    def _n_reviewer(self, state: GraphState) -> GraphState:
        eph, per = state["ephemeral"], state["persistent"]
        per.counters.bump("reviewer")
        crumb = NodeBreadcrumb(node="reviewer", trace_id=eph.trace_id, summary="reviewing")
        eph.push(crumb)
        sandbox = state.get("sandbox_result", {})
        drift = state.get("drift_result", {})
        verdict = self.reviewer.review(
            run_id=per.run_id, trace_id=eph.trace_id,
            drift_summary=drift.get("summary", "no-drift"),
            sandbox_excerpt=sandbox.get("stdout_excerpt", ""),
            sandbox_passed=bool(sandbox.get("passed")),
            sandbox_failure_type=sandbox.get("failure_type"),
            spec_paths=per.spec_paths,
        )
        state["review"] = verdict
        if verdict["verdict"] == "FAIL":
            ft = FailureType(verdict["failure_type"]) if verdict["failure_type"] in FailureType.__members__ else FailureType.UNKNOWN
            self._record_failure(state, ft, verdict.get("summary", "")[:200] or "reviewer-fail", node="reviewer",
                                 trace_path=sandbox.get("trace_path"))
        return state

    def _n_artifact(self, state: GraphState) -> GraphState:
        """drift + sandbox 통과한 patches를 실 디스크에 원자적 드롭.

        FilesystemPolicy 화이트리스트 위반은 PathTraversalError로 즉시 차단되고
        SECURITY_VIOLATION FailureRecord를 남긴다.
        """
        eph, per = state["ephemeral"], state["persistent"]
        crumb = NodeBreadcrumb(node="artifact", trace_id=eph.trace_id, summary="dropping")
        eph.push(crumb)
        patches = state.get("patches", {}).get("patches", [])  # type: ignore[typeddict-item]
        written: list[dict[str, Any]] = []
        for patch in patches:
            target = Path(patch["target_file"])
            try:
                meta = self.artifacts.write_section(
                    target, patch["body"], patch.get("section_id", "default"),
                )
            except PathTraversalError as exc:
                self._record_failure(
                    state, FailureType.SECURITY_VIOLATION,
                    f"artifact write traversal: {exc}"[:240], node="artifact",
                )
                # 즉시 HITL — 보안 위반은 사일런트 통과 불가.
                raise
            eph.last_artifact_path = meta.path
            written.append({
                "path": meta.path, "sha256": meta.sha256, "section": meta.section_id,
                "bytes": meta.bytes_written,
            })
        per.manifest.entry_count = len(written) + per.manifest.entry_count
        per.manifest.last_updated = eph.breadcrumbs[-1].entered_at
        state["artifacts"] = written  # type: ignore[typeddict-unknown-key]
        # staging 정리
        self._cleanup_staging(state)
        self.telemetry.event("artifact", "ok", eph.trace_id, run_id=per.run_id,
                             count=len(written))
        return state

    def _cleanup_staging(self, state: GraphState) -> None:
        staging = state.get("staging_dir")  # type: ignore[typeddict-item]
        if staging:
            shutil.rmtree(staging, ignore_errors=True)
            state["staging_dir"] = ""  # type: ignore[typeddict-unknown-key]

    def _n_hitl(self, state: GraphState) -> GraphState:
        eph, per = state["ephemeral"], state["persistent"]
        eph.awaiting_hitl = True
        self._cleanup_staging(state)
        self.hitl.trigger(per, trace_id=eph.trace_id, run_id=per.run_id)
        return state

    # === Helpers ===

    def _initial_state(self) -> GraphState:
        run_id = self.telemetry.new_run_id()
        trace_id = self.telemetry.new_trace_id()
        return GraphState(
            ephemeral=EphemeralState(trace_id=trace_id),
            persistent=PersistentState(run_id=run_id),
        )

    def _bind_llm(self) -> Callable[[str, str], str]:
        if self.llm_adapter is None:
            return _stub_llm

        from infrastructure.adapters import LLMRequest

        adapter = self.llm_adapter

        def _call(system: str, user: str, static_spec: str = "") -> str:
            req = LLMRequest(
                system_prompt=system, user_prompt=user,
                static_spec_context=static_spec,
                temperature=LLM_TEMPERATURE,  # 결정성 강제
            )
            return adapter.complete(req).text

        return _call

    def _traces_dir(self) -> Path:
        env = os.environ.get("STORAGE_TRACES_DIR")
        traces = Path(env) if env else (self.project_root / "storage" / "traces")
        traces.mkdir(parents=True, exist_ok=True)
        return traces

    def _to_storage_rel(self, p: Path) -> str:
        """trace 파일 경로를 항상 'storage/traces/...' 상대 경로로 정규화.

        FailureRecord 검증 규칙은 prefix='storage/traces/'를 강제한다.
        cwd 의존을 제거하고 self.project_root 기준으로 산출한다.
        """
        try:
            rel = p.resolve().relative_to(self.project_root.resolve())
        except ValueError:
            # 다른 드라이브 등 — fallback: filename만 storage/traces/ 하위로 표기.
            rel = Path("storage") / "traces" / p.name
        return str(rel).replace("\\", "/")

    def _record_failure(
        self,
        state: GraphState,
        failure_type: FailureType,
        summary: str,
        node: str,
        trace_path: Optional[str] = None,
    ) -> None:
        eph, per = state["ephemeral"], state["persistent"]
        if trace_path is None:
            tp = trace_path_for(node, self._traces_dir())
            tp.write_text(f"{failure_type.value} | {summary}\n", encoding="utf-8")
            trace_path = self._to_storage_rel(tp)
        record = FailureRecord(
            failure_type=failure_type, summary=summary[:240],
            trace_path=trace_path, node=node, attempt=per.counters.total,
        )
        eph.last_failure = record
        per.record_failure(record)

    def _record_exception(self, state: GraphState, exc: BaseException, node: str) -> None:
        tp = trace_path_for(node, self._traces_dir())
        tp.write_text("".join(traceback.format_exception(exc)), encoding="utf-8")
        self._record_failure(
            state, FailureType.from_exception(exc),
            f"{type(exc).__name__}: {exc}"[:240], node=node,
            trace_path=self._to_storage_rel(tp),
        )

    def _do_hitl(self, state: GraphState) -> dict[str, Any]:
        eph, per = state["ephemeral"], state["persistent"]
        eph.awaiting_hitl = True
        self._cleanup_staging(state)
        payload = self.hitl.trigger(per, trace_id=eph.trace_id, run_id=per.run_id)
        return self._finalize(state, status="HITL", extra={"hitl_payload": payload})

    def _finalize(self, state: GraphState, status: str, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        eph, per = state["ephemeral"], state["persistent"]
        result: dict[str, Any] = {
            "status": status,
            "run_id": per.run_id,
            "trace_id": eph.trace_id,
            "counters": per.counters.model_dump(),
            "last_artifact": eph.last_artifact_path,
            "last_failure": (eph.last_failure.model_dump() if eph.last_failure else None),
            "review": state.get("review"),
            "drift_result": state.get("drift_result"),
            "sandbox_result": state.get("sandbox_result"),
        }
        if extra:
            result.update(extra)
        self.telemetry.event("workflow", "finalize", eph.trace_id,
                             run_id=per.run_id, status=status)
        return result


def build_workflow(project_root: Optional[Path] = None, llm_adapter: Any = None) -> FactoryWorkflow:
    root = project_root or Path(__file__).resolve().parents[2]
    return FactoryWorkflow(project_root=root, llm_adapter=llm_adapter)


def main() -> int:
    """CLI 진입점 — .env의 LLM_ENGINE 설정에 따라 어댑터를 주입하여 파이프라인 가동."""
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    engine = os.environ.get("LLM_ENGINE", "hybrid").lower()
    adapter = None

    if engine == "hybrid":
        if os.environ.get("OPENAI_API_KEY") and os.environ.get("DEEPSEEK_API_KEY"):
            from infrastructure.adapters.openai import OpenAIAdapter
            from infrastructure.adapters.deepseek import DeepSeekAdapter
            from infrastructure.adapters.hybrid import HybridAdapter
            cheap = OpenAIAdapter(model="gpt-4o-mini")
            smart = DeepSeekAdapter(model="deepseek-chat")
            adapter = HybridAdapter(cheap_adapter=cheap, smart_adapter=smart)
            print("[Harness Engine] 하이브리드 어댑터 장착 완료 (Planner/Reviewer: GPT-4o-mini, Engineer: DeepSeek)")
        else:
            print("[Harness Engine] 경고: 하이브리드 모드이나 API KEY(OPENAI_API_KEY, DEEPSEEK_API_KEY)가 누락되어 Stub LLM이 사용됩니다.")
    
    elif engine == "claude":
        if os.environ.get("ANTHROPIC_API_KEY"):
            from infrastructure.adapters.claude import ClaudeAdapter
            adapter = ClaudeAdapter()
            print("[Harness Engine] 클로드 어댑터 장착 완료 (전체 에이전트: Claude 3.5 Sonnet)")
        else:
            print("[Harness Engine] 경고: 클로드 모드이나 ANTHROPIC_API_KEY가 누락되어 Stub LLM이 사용됩니다.")
            
    elif engine == "openai":
        if os.environ.get("OPENAI_API_KEY"):
            from infrastructure.adapters.openai import OpenAIAdapter
            adapter = OpenAIAdapter(model="gpt-4o")
            print("[Harness Engine] OpenAI 어댑터 장착 완료 (전체 에이전트: GPT-4o)")
        else:
            print("[Harness Engine] 경고: OpenAI 모드이나 OPENAI_API_KEY가 누락되어 Stub LLM이 사용됩니다.")
            
    else:
        print(f"[Harness Engine] 경고: 알 수 없는 LLM_ENGINE '{engine}'. Stub LLM이 사용됩니다.")

    wf = build_workflow(llm_adapter=adapter)
    try:
        result = wf.run_once()
    except HITLInterrupt as exc:
        try:
            print(json.dumps({"status": "HITL", "payload": exc.payload}, ensure_ascii=False, indent=2, default=str))
        except UnicodeEncodeError:
            print(json.dumps({"status": "HITL", "payload": exc.payload}, ensure_ascii=True, indent=2, default=str))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
# END GENERATED
