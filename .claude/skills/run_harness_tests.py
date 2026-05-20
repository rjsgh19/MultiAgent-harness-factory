# @generated
"""Claude CLI 커스텀 스킬 — 샌드박스 구동 트리거.

이 스크립트는 `.claude/skills/`에 위치하며, Claude CLI가
'TDD 하네스 실행' 요청을 받았을 때 호출하는 외부 진입점이다.
실제 로직은 `harness_engine.services.sandbox_runner`에 위임한다.
"""
# BEGIN GENERATED
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가하여 harness_engine 모듈 import 가능하도록 함
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Sandbox-isolated harness test runner")
    parser.add_argument("--target", default="my-harness-platform/tests", help="pytest target dir")
    parser.add_argument("--timeout", type=int, default=120, help="seconds")
    args = parser.parse_args()

    from harness_engine.services.sandbox_runner import SandboxRunner, SandboxConfig

    runner = SandboxRunner(SandboxConfig(timeout_seconds=args.timeout))
    result = runner.run_tests(target=args.target)
    print(f"[skill] sandbox exit_code={result.exit_code} failure_type={result.failure_type}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
# END GENERATED
