# @generated
"""Rootless Docker 기반 격리 테스트 실행기.

- 절대로 호스트 셸을 통해 pytest를 실행하지 않는다.
- Docker SDK가 없거나 데몬에 접근 불가하면 명확하게 INFRA_TIMEOUT/SECURITY_VIOLATION을 보고하고 호스트 폴백을 거부한다.
- 강력한 timeout, 메모리/CPU 제한, network=none, read-only 마운트를 적용한다.
- 모든 stdout/stderr는 storage/traces/ 외부 파일로 격리 저장 (State에는 경로만).
"""
# BEGIN GENERATED
from __future__ import annotations

import os
import shlex
import tarfile
import io
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from harness_engine.state.failure_types import FailureType, trace_path_for
from harness_engine.services.telemetry import get_telemetry


@dataclass(frozen=True)
class SandboxConfig:
    image: str = os.environ.get("SANDBOX_DOCKER_IMAGE", "python:3.11-slim")
    timeout_seconds: int = int(os.environ.get("SANDBOX_TIMEOUT_SECONDS", "120"))
    memory_limit: str = os.environ.get("SANDBOX_MEMORY_LIMIT", "512m")
    cpu_quota: int = int(os.environ.get("SANDBOX_CPU_QUOTA", "50000"))  # 50% of single CPU
    workdir: str = "/sandbox"
    # Defaults는 사전 빌드 이미지를 가정한다: pytest 가 이미 들어 있는 이미지를 사용하고
    # network는 차단된 상태에서 동작한다. pip 다운로드가 필요한 경우만 명시적으로
    # SANDBOX_ALLOW_PIP=1 으로 일시 활성화해야 한다.
    network_disabled: bool = os.environ.get("SANDBOX_ALLOW_PIP", "0") != "1"
    read_only_root: bool = True
    skip_pip: bool = os.environ.get("SANDBOX_ALLOW_PIP", "0") != "1"
    pip_install: tuple[str, ...] = ("pytest",)
    traces_dir: Path = field(default_factory=lambda: Path(os.environ.get("STORAGE_TRACES_DIR", "storage/traces")))


@dataclass(frozen=True)
class SandboxResult:
    passed: bool
    exit_code: int
    duration_seconds: float
    failure_type: Optional[FailureType]
    trace_path: Optional[str]   # storage/traces/ 상대 경로 (State 바인딩용)
    stdout_excerpt: str          # 최대 240자 발췌 (State는 절대 본문 누적 X)


class SandboxRunner:
    """Docker 격리 pytest 실행기."""

    def __init__(self, config: Optional[SandboxConfig] = None) -> None:
        self.config = config or SandboxConfig()
        self.config.traces_dir.mkdir(parents=True, exist_ok=True)
        self._telemetry = get_telemetry()

    def run_tests(self, target: str = "my-harness-platform/tests", trace_id: Optional[str] = None) -> SandboxResult:
        trace_id = trace_id or self._telemetry.new_trace_id()
        started = time.monotonic()
        trace_file = trace_path_for("sandbox", self.config.traces_dir)
        try:
            import docker  # type: ignore
        except ImportError as exc:
            return self._fail(
                trace_file, FailureType.SECURITY_VIOLATION, started, trace_id,
                f"docker SDK 미설치 — 호스트 폴백 거부: {exc}",
            )

        try:
            client = docker.from_env()
            client.ping()
        except Exception as exc:  # noqa: BLE001 — Docker 데몬 접근 자체가 광범위 예외 가능
            return self._fail(
                trace_file, FailureType.INFRA_TIMEOUT, started, trace_id,
                f"docker 데몬 접근 실패: {exc!r}",
            )

        host_target = Path(target).resolve()
        if not host_target.exists():
            return self._fail(
                trace_file, FailureType.UNKNOWN, started, trace_id,
                f"테스트 타겟 경로 부재: {host_target}",
            )

        cmd = self._build_command()
        self._telemetry.event(
            "sandbox", "spawn", trace_id, image=self.config.image,
            timeout=self.config.timeout_seconds, cmd=cmd,
        )

        container = None
        try:
            container = client.containers.create(
                image=self.config.image,
                command=["/bin/sh", "-c", cmd],
                working_dir=self.config.workdir,
                network_disabled=self.config.network_disabled,
                mem_limit=self.config.memory_limit,
                nano_cpus=self.config.cpu_quota * 1000,  # cpu_quota microseconds → nano
                detach=True,
                tty=False,
                user="1000:1000",  # rootless
                read_only=self.config.read_only_root,
                tmpfs={"/tmp": "rw,size=128m", self.config.workdir: "rw,size=256m"},
                environment={"PYTHONDONTWRITEBYTECODE": "1", "PIP_NO_CACHE_DIR": "1"},
            )
            self._upload_workspace(container, host_target)
            container.start()
            try:
                result = container.wait(timeout=self.config.timeout_seconds)
            except Exception as exc:  # docker.errors.ConnectionError / ReadTimeout
                self._safe_kill(container)
                return self._fail(
                    trace_file, FailureType.INFRA_TIMEOUT, started, trace_id,
                    f"sandbox timeout 초과 ({self.config.timeout_seconds}s) — {exc!r}",
                )
            exit_code = int(result.get("StatusCode", -1))
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
            trace_file.write_text(logs, encoding="utf-8")

            failure_type = None if exit_code == 0 else self._classify(logs)
            duration = time.monotonic() - started
            self._telemetry.event(
                "sandbox", "exit", trace_id,
                exit_code=exit_code, duration_sec=round(duration, 3),
                trace_path=str(self._rel(trace_file)),
            )
            return SandboxResult(
                passed=exit_code == 0,
                exit_code=exit_code,
                duration_seconds=duration,
                failure_type=failure_type,
                trace_path=str(self._rel(trace_file)),
                stdout_excerpt=self._excerpt(logs),
            )
        except Exception as exc:  # noqa: BLE001
            return self._fail(
                trace_file, FailureType.from_exception(exc), started, trace_id,
                f"sandbox 예외: {exc!r}",
            )
        finally:
            self._safe_remove(container)

    # === Internal ===

    def _build_command(self) -> str:
        # 디폴트는 사전 빌드 이미지 가정 → pip install 단계 생략.
        # network가 차단된 채로 pip를 시도하면 항상 실패하므로 정책적으로 일치시킨다.
        if self.config.skip_pip:
            return "python -m pytest --maxfail=5 -q ."
        pip = " ".join(shlex.quote(p) for p in self.config.pip_install)
        return f"pip install --quiet {pip} && python -m pytest --maxfail=5 -q ."

    def _upload_workspace(self, container, host_target: Path) -> None:
        """호스트 테스트 폴더를 컨테이너 /sandbox로 tar 스트림 전송."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            tar.add(str(host_target), arcname=".")
        buf.seek(0)
        container.put_archive(self.config.workdir, buf.getvalue())

    def _classify(self, logs: str) -> FailureType:
        low = logs.lower()
        if "syntaxerror" in low:
            return FailureType.SYNTAX
        if "importerror" in low or "modulenotfounderror" in low:
            return FailureType.IMPORT_ERROR
        if "typeerror" in low:
            return FailureType.TYPE_ERROR
        if "assertionerror" in low or "failed" in low and "passed" not in low:
            return FailureType.TEST_ASSERTION
        if "killed" in low or "memoryerror" in low:
            return FailureType.RESOURCE_LIMIT
        if "permission denied" in low:
            return FailureType.SECURITY_VIOLATION
        return FailureType.UNKNOWN

    @staticmethod
    def _excerpt(text: str, limit: int = 240) -> str:
        single = " ".join(text.splitlines())[:limit]
        return single

    def _rel(self, p: Path) -> Path:
        cwd = Path.cwd().resolve()
        try:
            return p.resolve().relative_to(cwd)
        except ValueError:
            return p

    def _fail(self, trace_file: Path, ft: FailureType, started: float, trace_id: str, msg: str) -> SandboxResult:
        trace_file.write_text(
            f"[{datetime.now(timezone.utc).isoformat()}] {ft.value}\n{msg}\n",
            encoding="utf-8",
        )
        self._telemetry.error("sandbox", trace_id, msg, failure_type=ft.value)
        return SandboxResult(
            passed=False,
            exit_code=-1,
            duration_seconds=time.monotonic() - started,
            failure_type=ft,
            trace_path=str(self._rel(trace_file)),
            stdout_excerpt=self._excerpt(msg),
        )

    @staticmethod
    def _safe_kill(container) -> None:
        try:
            container.kill()
        except Exception:
            pass

    @staticmethod
    def _safe_remove(container) -> None:
        if container is None:
            return
        try:
            container.remove(force=True)
        except Exception:
            pass


def main() -> int:
    """CLI 진입점 — 기본 디렉토리에 대해 샌드박스 채점."""
    runner = SandboxRunner()
    res = runner.run_tests()
    print(f"passed={res.passed} exit={res.exit_code} ft={res.failure_type} trace={res.trace_path}")
    return 0 if res.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
# END GENERATED
