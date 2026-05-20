# @generated
"""파일시스템 허용 범위 통제 엔진.

artifact_writer는 어떤 경로에도 쓸 수 있는 것이 아니라
정의된 화이트리스트 (`my-harness-platform/src`, `my-harness-platform/tests`)
하위로만 쓰기를 허용받는다. 본 모듈은 그 경계선을 코드로 강제한다.
"""
# BEGIN GENERATED
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class FilesystemPolicyViolation(PermissionError):
    """경계 밖 경로에 쓰기를 시도했을 때 발생."""


@dataclass(frozen=True)
class FilesystemPolicy:
    project_root: Path
    writable_roots: tuple[Path, ...]

    @classmethod
    def default(cls, project_root: Path) -> "FilesystemPolicy":
        return cls(
            project_root=project_root.resolve(),
            writable_roots=(
                (project_root / "my-harness-platform" / "src").resolve(),
                (project_root / "my-harness-platform" / "tests").resolve(),
                (project_root / "storage").resolve(),
            ),
        )

    def assert_writable(self, target: Path) -> Path:
        resolved = target.resolve()
        for root in self.writable_roots:
            try:
                resolved.relative_to(root)
                return resolved
            except ValueError:
                continue
        raise FilesystemPolicyViolation(
            f"쓰기 금지 영역: {resolved} (허용: {[str(r) for r in self.writable_roots]})"
        )

    def is_protected(self, target: Path) -> bool:
        try:
            self.assert_writable(target)
            return False
        except FilesystemPolicyViolation:
            return True
# END GENERATED
