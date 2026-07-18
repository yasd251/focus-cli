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
    paused_at: Optional[float] = None
    paused_seconds: float = 0.0

    @property
    def planned_seconds(self) -> int:
        return self.planned_minutes * 60

    def focused_seconds_at(self, now: float) -> int:
        """Return elapsed focus time, excluding every paused interval."""

        if self.actual_seconds is not None:
            return self.actual_seconds
        effective_now = self.paused_at if self.paused_at is not None else now
        elapsed = effective_now - self.started_at - self.paused_seconds
        return max(0, min(self.planned_seconds, int(elapsed)))

    def remaining_seconds_at(self, now: float) -> int:
        """Return whole seconds remaining, with a paused timer held still."""

        return max(0, self.planned_seconds - self.focused_seconds_at(now))


@dataclass(frozen=True)
class FinalizedSession:
    session: Session
    total_xp: int


@dataclass(frozen=True)
class CreateSessionResult:
    created: Optional[Session]
    existing: Optional[Session]
    recovered: Optional[FinalizedSession]


@dataclass(frozen=True)
class PauseSessionResult:
    paused: Optional[Session]
    existing: Optional[Session]
    completed: Optional[FinalizedSession]


@dataclass(frozen=True)
class ResumeSessionResult:
    resumed: Optional[Session]
    existing: Optional[Session]
