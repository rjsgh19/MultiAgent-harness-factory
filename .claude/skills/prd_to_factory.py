# @generated
"""PRD → 공장 문서 자동 생성 스킬 (메인 CLI).

사용법:
  python .claude/skills/prd_to_factory.py --prd docs/prd/vertiport_prd.md
  python .claude/skills/prd_to_factory.py --prd docs/prd/vertiport_prd.md --dry-run
  python .claude/skills/prd_to_factory.py --prd docs/prd/vertiport_prd.md --use-llm
"""
# BEGIN GENERATED
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SKILLS_DIR = Path(__file__).resolve().parent
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))

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

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="PRD 마크다운 → 하네스 공장 문서 자동 생성 (100% LLM 파싱 기반)",
    )
    parser.add_argument("--prd", required=True, help="PRD 마크다운 파일 경로")
    parser.add_argument("--dry-run", action="store_true", help="실제 파일 쓰기 없이 미리보기")
    args = parser.parse_args()

    prd_path = Path(args.prd)
    if not prd_path.is_absolute():
        prd_path = ROOT / prd_path
    dry_run = args.dry_run

    if not prd_path.exists():
        print(f"[prd_to_factory] ❌ PRD 파일을 찾을 수 없습니다: {prd_path}")
        return 1

    print(f"[prd_to_factory] PRD LLM 파싱 준비 중: {prd_path}")
    
    # === 1. LLM 어댑터 확인 ===
    llm_fn, err_msg = _try_get_llm_adapter()
    if not llm_fn:
        print("[prd_to_factory] [X] LLM 어댑터를 생성할 수 없습니다.")
        if err_msg:
            print(f"  이유: {err_msg}")
        print("  .env 파일의 설정 및 파이썬 의존성 패키지(python-dotenv, openai 등) 설치 여부를 확인해주세요.")
        return 1

    # === 2. 100% LLM 기반 PRD 파싱 ===
    from llm_enricher import parse_prd_with_llm, validate_parsed_prd_with_llm
    
    raw_markdown = prd_path.read_text(encoding="utf-8")
    print("[prd_to_factory] LLM으로 PRD 마크다운 분석 중... (수 초~십여 초 소요)")
    
    try:
        prd = parse_prd_with_llm(raw_markdown, llm_complete=llm_fn)
    except Exception as e:
        print(f"[prd_to_factory] ❌ LLM 파싱 실패: {e}")
        return 1

    print("[prd_to_factory] LLM 환각(Hallucination) 방지 교차 검증 중...")
    validation_errors = validate_parsed_prd_with_llm(raw_markdown, prd, llm_fn)
    if validation_errors:
        print("[prd_to_factory] ⚠️ 주의: 추출된 데이터가 원본 PRD와 일치하지 않을 수 있습니다.")
        for err in validation_errors:
            print(f"  - {err}")
        print("계속 진행하시려면 엔터를 누르세요 (취소: Ctrl+C)")
        try:
            input()
        except KeyboardInterrupt:
            print("\n[prd_to_factory] 작업을 취소합니다.")
            return 1
    else:
        print("[prd_to_factory] 교차 검증 통과 ✅ (지어낸 내용 없음)")

    domain = prd.get("domain", prd_path.stem)
    print(f"[prd_to_factory] PRD 파싱 완료: {prd.get('project_name', domain)} (domain={domain})")
    print(f"  함수: {len(prd.get('functions', []))}개, "
          f"에이전트: {len(prd.get('agents', []))}개, "
          f"테스트: {len(prd.get('tests', []))}개")

    # === 3. 문서 생성 ===
    from generators import (
        GeneratorResult,
        generate_domain_spec,
        generate_workflow_spec,
        merge_architecture_policy,
        generate_agent_guide,
        augment_factory_guides,
        generate_test_scaffold,
    )

    result = GeneratorResult()
    specs_dir = ROOT / "agent_runtime" / "specifications"
    guides_dir = ROOT / "docs" / "agent_guides"
    tests_root = ROOT / "my-harness-platform" / "tests"

    if dry_run:
        print("\n[prd_to_factory] === DRY RUN (실제 파일 쓰기 없음) ===\n")

    # 3a. 도메인 명세 YAML
    path, _ = generate_domain_spec(prd, specs_dir, dry_run=dry_run)
    result.created.append(str(path.relative_to(ROOT)))

    # 3b. 워크플로 명세 YAML
    path, _ = generate_workflow_spec(prd, specs_dir, dry_run=dry_run)
    result.created.append(str(path.relative_to(ROOT)))

    # 3c. 아키텍처 정책 머지
    path, changed = merge_architecture_policy(prd, specs_dir, dry_run=dry_run)
    if changed:
        result.modified.append(str(path.relative_to(ROOT)))
    else:
        result.skipped.append(str(path.relative_to(ROOT)))

    # 3d. 공장 가이드 보강
    guide_results = augment_factory_guides(prd, guides_dir, dry_run=dry_run)
    for path, changed in guide_results:
        rel = str(path.relative_to(ROOT))
        if changed:
            result.modified.append(rel)
        else:
            result.skipped.append(rel)

    # 3e. 앱 에이전트 가이드 생성
    project_slug = domain.split("_")[-1] if "_" in domain else domain
    for agent in prd.get("agents", []):
        path, _ = generate_agent_guide(agent, guides_dir, project_slug, dry_run=dry_run)
        result.created.append(str(path.relative_to(ROOT)))

    # 3f. 테스트 스캐폴드 생성
    for test in prd.get("tests", []):
        path, _ = generate_test_scaffold(
            test,
            tests_root,
            prd=prd,
            raw_markdown=raw_markdown,
            llm_complete=llm_fn,
            dry_run=dry_run,
        )
        result.created.append(str(path.relative_to(ROOT)))

    # === 4. 검증 ===
    print(f"\n[prd_to_factory] --- 생성 결과 ---")
    print(result.report())

    if not dry_run:
        print(f"\n[prd_to_factory] --- 검증 ---")
        errors = _validate(specs_dir, guides_dir)
        if errors:
            for e in errors:
                print(f"  ❌ {e}")
            return 1
        else:
            print("  SpecLoader: 모든 spec 검증 통과 ✅")
            print("  PromptLoader: 모든 가이드 검증 통과 ✅")

    print(f"\n[prd_to_factory] 완료!")
    return 0


def _try_get_llm_adapter() -> tuple[any, str | None]:
    """LLM 어댑터 로드 시도. (callable_fn, error_msg) 반환."""
    try:
        import os
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            # python-dotenv가 없어도 시스템 환경변수를 사용할 수 있으므로 계속 진행
            pass
            
        from infrastructure.adapters import LLMRequest
        
        engine = os.environ.get("LLM_ENGINE", "hybrid").lower()
        adapter = None
        
        if engine == "hybrid":
            openai_key = os.environ.get("OPENAI_API_KEY")
            deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
            if not openai_key or not deepseek_key:
                missing = []
                if not openai_key: missing.append("OPENAI_API_KEY")
                if not deepseek_key: missing.append("DEEPSEEK_API_KEY")
                return None, f"hybrid 엔진을 활성화하려면 다음 환경변수가 필요합니다: {', '.join(missing)}"
                
            from infrastructure.adapters.openai import OpenAIAdapter
            from infrastructure.adapters.deepseek import DeepSeekAdapter
            from infrastructure.adapters.hybrid import HybridAdapter
            adapter = HybridAdapter(
                cheap_adapter=OpenAIAdapter(model="gpt-4o-mini"),
                smart_adapter=DeepSeekAdapter(model="deepseek-chat")
            )
        elif engine == "claude":
            anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
            if not anthropic_key:
                return None, "claude 엔진을 활성화하려면 ANTHROPIC_API_KEY 환경변수가 필요합니다."
            from infrastructure.adapters.claude import ClaudeAdapter
            adapter = ClaudeAdapter()
        elif engine == "openai":
            openai_key = os.environ.get("OPENAI_API_KEY")
            if not openai_key:
                return None, "openai 엔진을 활성화하려면 OPENAI_API_KEY 환경변수가 필요합니다."
            from infrastructure.adapters.openai import OpenAIAdapter
            adapter = OpenAIAdapter(model="gpt-4o")
        else:
            return None, f"지원하지 않는 LLM_ENGINE 값입니다: {engine}"

        if adapter:
            def _call(system: str, user: str) -> str:
                # prd_to_factory는 코드 생성이 아니므로 저렴한 모델(Planner 역할)로 동작
                req = LLMRequest(system_prompt=system, user_prompt=user, temperature=0)
                return adapter.complete(req).text
            return _call, None

    except Exception as e:
        return None, f"어댑터 로딩 에러 ({type(e).__name__}): {e}"
        
    return None, "알 수 없는 이유로 어댑터를 생성하지 못했습니다."


def _validate(specs_dir: Path, guides_dir: Path) -> list[str]:
    """생성된 파일들을 SpecLoader + PromptLoader로 검증."""
    errors: list[str] = []
    try:
        from harness_engine.services.spec_loader import SpecLoader
        sl = SpecLoader()
        specs = sl.load_many(specs_dir)
        print(f"  SpecLoader: {len(specs)}개 spec 로드 완료")
    except Exception as e:
        errors.append(f"SpecLoader 실패: {e}")

    try:
        from harness_engine.services.prompt_loader import PromptLoader
        pl = PromptLoader()
        for f in guides_dir.rglob("*.md"):
            try:
                pl.load(f)
            except Exception as e:
                errors.append(f"PromptLoader({f.name}): {e}")
    except Exception as e:
        errors.append(f"PromptLoader 초기화 실패: {e}")

    return errors


if __name__ == "__main__":
    raise SystemExit(main())
# END GENERATED
