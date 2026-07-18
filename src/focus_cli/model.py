"""Domain models used by Focus CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Session:
    id: str
    title: Optional[str]
    planned_minutes: int
    started_at: float
    planned_end_at: float
    ended_at: Optional[float]
    actual_seconds: Optional[int]
    status: str
    base_xp: int
    bonus_xp: int
    xp_awarded: int
    created_at: float

    @property
    def planned_seconds(self) -> int:
        return self.planned_minutes * 60


@dataclass(frozen=True)
class FinalizedSession:
    session: Session
    total_xp: int


@dataclass(frozen=True)
class CreateSessionResult:
    created: Optional[Session]
    existing: Optional[Session]
    recovered: Optional[FinalizedSession]

