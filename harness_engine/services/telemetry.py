# @generated
"""Structured Logging + 가상 Trace ID 매핑기.

OpenTelemetry-api를 의존성으로 두되, 본 모듈은 OTLP 익스포터 없이도
동작하도록 fallback path를 보유한다. 핵심 책임:
1. run_id / trace_id / node 단위 구조화 로그 생성
2. storage/telemetry/ 하위에 JSON Lines 타임라인 파일 기록
3. 노드 진입/이탈 시각 통계 수집
"""
# BEGIN GENERATED
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


_DEFAULT_TELEMETRY_DIR = Path(os.environ.get("STORAGE_TELEMETRY_DIR", "storage/telemetry"))


@dataclass
class Telemetry:
    """구조화 로그 + 타임라인 기록기 (스레드세이프)."""

    service_name: str = "harness-automation-factory"
    telemetry_dir: Path = field(default_factory=lambda: _DEFAULT_TELEMETRY_DIR)
    log_level: int = logging.INFO
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _logger: logging.Logger = field(init=False, repr=False)
    _current_file: Optional[Path] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.telemetry_dir.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger(self.service_name)
        logger.setLevel(self.log_level)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(name)s %(message)s")
            )
            logger.addHandler(handler)
            logger.propagate = False
        self._logger = logger

    # === Trace ID 발행 ===

    @staticmethod
    def new_trace_id() -> str:
        return uuid.uuid4().hex

    @staticmethod
    def new_run_id() -> str:
        return f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"

    # === 로그 + 타임라인 기록 ===

    def event(
        self,
        node: str,
        kind: str,
        trace_id: str,
        run_id: Optional[str] = None,
        **fields: Any,
    ) -> None:
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "service": self.service_name,
            "run_id": run_id,
            "trace_id": trace_id,
            "node": node,
            "kind": kind,
        }
        record.update(self._safe_fields(fields))
        self._logger.info(json.dumps(record, ensure_ascii=False))
        self._append_timeline(record)

    def warning(self, node: str, trace_id: str, message: str, **fields: Any) -> None:
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "service": self.service_name,
            "trace_id": trace_id,
            "node": node,
            "kind": "warning",
            "message": message,
        }
        record.update(self._safe_fields(fields))
        self._logger.warning(json.dumps(record, ensure_ascii=False))
        self._append_timeline(record)

    def error(self, node: str, trace_id: str, message: str, **fields: Any) -> None:
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "service": self.service_name,
            "trace_id": trace_id,
            "node": node,
            "kind": "error",
            "message": message,
        }
        record.update(self._safe_fields(fields))
        self._logger.error(json.dumps(record, ensure_ascii=False))
        self._append_timeline(record)

    # === Internal helpers ===

    @staticmethod
    def _safe_fields(fields: dict[str, Any]) -> dict[str, Any]:
        """JSON 직렬화 불가능한 값은 repr로 강등."""
        out: dict[str, Any] = {}
        for k, v in fields.items():
            try:
                json.dumps(v)
                out[k] = v
            except (TypeError, ValueError):
                out[k] = repr(v)
        return out

    def _append_timeline(self, record: dict[str, Any]) -> None:
        with self._lock:
            if self._current_file is None:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
                self._current_file = self.telemetry_dir / f"timeline-{stamp}.jsonl"
            self._current_file.parent.mkdir(parents=True, exist_ok=True)
            with self._current_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")


_singleton: Optional[Telemetry] = None
_singleton_lock = threading.Lock()


def get_telemetry() -> Telemetry:
    """프로세스 전역 텔레메트리 싱글톤."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = Telemetry()
    return _singleton
# END GENERATED
