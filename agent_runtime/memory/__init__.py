# @generated
"""Ephemeral vs Persistent 메모리 격리 진입점.

Ephemeral: 현재 그래프 실행 한 사이클 동안만 유지되는 휘발성 메모리.
Persistent: 체크포인트(LangGraph checkpointer) 또는 영속 저장소에 적재.
"""
# BEGIN GENERATED
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EphemeralMemory:
    """워크플로우 1회 실행 안에서만 사용되는 휘발성 키-값."""

    data: dict[str, Any] = field(default_factory=dict)

    def put(self, key: str, value: Any) -> None:
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def clear(self) -> None:
        self.data.clear()


@dataclass
class PersistentMemory:
    """영속 메모리 — 체크포인트와 매핑되는 직렬화 가능 메타데이터 컨테이너."""

    namespace: str
    records: dict[str, Any] = field(default_factory=dict)

    def remember(self, key: str, value: Any) -> None:
        if not isinstance(value, (str, int, float, bool, list, dict)) and value is not None:
            raise TypeError(f"persistent memory는 직렬화 가능한 값만 허용 — got {type(value)}")
        self.records[key] = value

    def recall(self, key: str, default: Any = None) -> Any:
        return self.records.get(key, default)


__all__ = ["EphemeralMemory", "PersistentMemory"]
# END GENERATED
