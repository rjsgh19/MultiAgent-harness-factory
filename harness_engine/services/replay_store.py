# @generated
"""디터미니스틱 리플레이 스냅샷 저장소.

LLM 호출 1회마다 prompt / spec / tool output 스냅샷을 storage/replays/ 하위에
원자적으로 적재한다. 이는 실패 재현 및 회귀 검증의 기반이 된다.
"""
# BEGIN GENERATED
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class ReplaySnapshot:
    run_id: str
    trace_id: str
    node: str
    prompt: str
    spec_paths: list[str]
    tool_output: Any
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "node": self.node,
            "prompt": self.prompt,
            "spec_paths": self.spec_paths,
            "tool_output": self.tool_output,
            "created_at": self.created_at.isoformat(),
            # temperature는 워크플로우 차원에서 강제 — 기록만 남긴다.
            "llm_temperature": 0,
        }


class ReplayStore:
    """JSON 파일 기반 리플레이 적재기 — 원자적 write."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root or Path(os.environ.get("STORAGE_REPLAYS_DIR", "storage/replays"))
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, snapshot: ReplaySnapshot) -> Path:
        stamp = snapshot.created_at.strftime("%Y%m%dT%H%M%S%f")
        fname = f"{snapshot.run_id}__{snapshot.node}__{stamp}.json"
        target = self.root / fname
        payload = json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2)
        self._atomic_write(target, payload)
        return target

    def load(self, path: Path) -> dict[str, Any]:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def find_by_run(self, run_id: str) -> list[Path]:
        return sorted(self.root.glob(f"{run_id}__*.json"))

    @staticmethod
    def _atomic_write(target: Path, payload: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(payload)
            os.replace(tmp, target)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
# END GENERATED
