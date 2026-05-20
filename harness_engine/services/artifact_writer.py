# @generated
"""구간 기반 패치 + 매니페스트 위변조 검증 라이터.

핵심 보장:
1. 파일 상단에 `# @generated` 마커가 반드시 존재해야 한다.
2. 패치는 오직 `# BEGIN GENERATED [section_id]` ~ `# END GENERATED [section_id]`
   구간 안의 본문만 교체한다. 인간 영역은 절대 덮어쓰지 않는다.
3. 기존 파일에 마커가 유실되어 있다면 `OverwriteError`를 발동.
4. `.generated_manifest.json`에 SHA-256 해시 + 모드 + 갱신 시각을 원자적으로 기록한다.
"""
# BEGIN GENERATED
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agent_runtime.policy_engine.filesystem_policy import (
    FilesystemPolicy,
    FilesystemPolicyViolation,
)


_MARKER_FILE = "# @generated"
_BEGIN = "# BEGIN GENERATED"
_END = "# END GENERATED"


class OverwriteError(RuntimeError):
    """마커 유실 또는 매니페스트 위변조 감지 시 발생."""


class PathTraversalError(PermissionError):
    """artifact_writer가 화이트리스트 밖 경로 작성 시도를 차단할 때 발생."""


@dataclass(frozen=True)
class ArtifactMetadata:
    path: str
    sha256: str
    section_id: str
    bytes_written: int
    written_at: datetime
    manifest_path: str


@dataclass
class ArtifactWriter:
    """`# BEGIN/END GENERATED` 구간 기반 안전 라이터.

    FilesystemPolicy 화이트리스트(`my-harness-platform/src`, `tests`, `storage`)
    밖 경로로의 모든 작성을 즉시 PathTraversalError로 차단한다.
    """

    project_root: Path
    policy: FilesystemPolicy = field(init=False)
    manifest_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.policy = FilesystemPolicy.default(self.project_root)
        self.manifest_path = (
            self.project_root / "my-harness-platform" / ".generated_manifest.json"
        ).resolve()
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            self._atomic_write_text(
                self.manifest_path,
                json.dumps(
                    {"version": "1.0", "updated_at": None, "entries": {}},
                    ensure_ascii=False,
                    indent=2,
                ),
            )

    # === Public API ===

    def write_section(
        self,
        path: Path,
        content: str,
        section_id: str = "default",
    ) -> ArtifactMetadata:
        target = self._normalize_target(path)
        # 1) Path Traversal 차단 — 화이트리스트 밖이면 즉시 거부.
        try:
            self.policy.assert_writable(target)
        except FilesystemPolicyViolation as exc:
            raise PathTraversalError(str(exc)) from exc
        # 2) 매니페스트 무결성 검증 (외부 수정 감지).
        self._verify_manifest_integrity()
        body_to_write = self._compose(target, content, section_id)
        self._atomic_write_text(target, body_to_write)
        sha = hashlib.sha256(target.read_bytes()).hexdigest()
        meta = ArtifactMetadata(
            path=str(self._rel(target)),
            sha256=sha,
            section_id=section_id,
            bytes_written=len(body_to_write.encode("utf-8")),
            written_at=datetime.now(timezone.utc),
            manifest_path=str(self._rel(self.manifest_path)),
        )
        self._record(meta)
        return meta

    def verify_existing(self, path: Path) -> bool:
        """기존 파일의 매니페스트 무결성을 검증."""
        target = self._normalize_target(path)
        if not target.exists():
            return False
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        data = self._load_manifest()
        entry = data.get("entries", {}).get(str(self._rel(target)))
        return bool(entry and entry.get("sha256") == actual)

    # === Internal: composition ===

    def _compose(self, target: Path, content: str, section_id: str) -> str:
        body = content.rstrip() + "\n"
        begin_token = f"{_BEGIN}" if section_id == "default" else f"{_BEGIN} [{section_id}]"
        end_token = f"{_END}" if section_id == "default" else f"{_END} [{section_id}]"

        if not target.exists():
            header = f"{_MARKER_FILE}\n"
            block = f"{begin_token}\n{body}{end_token}\n"
            return header + block

        existing = target.read_text(encoding="utf-8")
        if _MARKER_FILE not in existing.splitlines()[:3]:
            raise OverwriteError(
                f"기존 파일에 '@generated' 마커 유실: {target} — 인간 작성 파일을 덮어쓸 수 없음"
            )

        if begin_token in existing and end_token in existing:
            pattern = re.compile(
                re.escape(begin_token) + r".*?" + re.escape(end_token),
                flags=re.DOTALL,
            )
            replaced = pattern.sub(
                lambda _m: f"{begin_token}\n{body}{end_token}",
                existing,
                count=1,
            )
            return replaced

        # 새 섹션 추가 — 파일 말미에 append (인간 영역은 손대지 않음)
        if not existing.endswith("\n"):
            existing += "\n"
        return existing + f"{begin_token}\n{body}{end_token}\n"

    # === Internal: manifest ===

    def _record(self, meta: ArtifactMetadata) -> None:
        data = self._load_manifest()
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        entries = data.setdefault("entries", {})
        entries[meta.path] = {
            "sha256": meta.sha256,
            "section_id": meta.section_id,
            "bytes": meta.bytes_written,
            "written_at": meta.written_at.isoformat(),
        }
        self._atomic_write_text(
            self.manifest_path, json.dumps(data, ensure_ascii=False, indent=2)
        )

    def _verify_manifest_integrity(self) -> None:
        """매니페스트가 가리키는 기존 파일들의 해시가 실제와 일치하는지 검증."""
        data = self._load_manifest()
        for rel, entry in data.get("entries", {}).items():
            p = (self.project_root / rel).resolve()
            if not p.exists():
                # 외부 삭제는 경고만 (다음 write에서 재기록)
                continue
            actual = hashlib.sha256(p.read_bytes()).hexdigest()
            if actual != entry.get("sha256"):
                raise OverwriteError(
                    f"매니페스트 위변조 또는 외부 수정 감지: {rel} (expected {entry['sha256'][:12]}, got {actual[:12]})"
                )

    def _load_manifest(self) -> dict:
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"version": "1.0", "updated_at": None, "entries": {}}

    # === Internal: I/O ===

    def _normalize_target(self, path: Path) -> Path:
        if path.is_absolute():
            return path.resolve()
        return (self.project_root / path).resolve()

    def _rel(self, p: Path) -> Path:
        try:
            return p.relative_to(self.project_root.resolve())
        except ValueError:
            return p

    @staticmethod
    def _atomic_write_text(target: Path, text: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".tmp_", suffix=target.suffix, dir=str(target.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def _is_protected_path(path: Path, allowed_roots: tuple[Path, ...]) -> Optional[str]:
    """allowed_roots 밖의 경로면 위반 이유 문자열 반환, 안이면 None."""
    resolved = path.resolve()
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return None
        except ValueError:
            continue
    return f"target path '{resolved}' outside allowed roots"
# END GENERATED
