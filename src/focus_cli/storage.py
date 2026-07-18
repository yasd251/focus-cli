"""SQLite-backed persistence for focus sessions."""

from __future__ import annotations

import math
import os
import platform
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Optional

from .model import (
    CreateSessionResult,
    FinalizedSession,
    PauseSessionResult,
    ResumeSessionResult,
    Session,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NULL,
    planned_minutes INTEGER NOT NULL CHECK (planned_minutes BETWEEN 1 AND 1440),
    started_at REAL NOT NULL,
    planned_end_at REAL NOT NULL,
    ended_at REAL NULL,
    actual_seconds INTEGER NULL CHECK (actual_seconds IS NULL OR actual_seconds >= 0),
    status TEXT NOT NULL CHECK (status IN ('active', 'completed', 'stopped')),
    base_xp INTEGER NOT NULL DEFAULT 0 CHECK (base_xp >= 0),
    bonus_xp INTEGER NOT NULL DEFAULT 0 CHECK (bonus_xp >= 0),
    xp_awarded INTEGER NOT NULL DEFAULT 0 CHECK (xp_awarded >= 0),
    created_at REAL NOT NULL,
    paused_at REAL NULL,
    paused_seconds REAL NOT NULL DEFAULT 0 CHECK (paused_seconds >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS sessions_one_active
    ON sessions(status)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS sessions_created_at
    ON sessions(created_at DESC);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def default_database_path() -> Path:
    """Return the platform-appropriate database path.

    ``FOCUS_DB_PATH`` is intentionally supported for portable installs and tests.
    ``FOCUS_DATA_DIR`` can instead override only the containing directory.
    """

    explicit_path = os.environ.get("FOCUS_DB_PATH")
    if explicit_path:
        return Path(explicit_path).expanduser()

    explicit_dir = os.environ.get("FOCUS_DATA_DIR")
    if explicit_dir:
        return Path(explicit_dir).expanduser() / "focus.db"

    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        return home / "Library" / "Application Support" / "focus" / "focus.db"
    if system == "Windows":
        app_data = os.environ.get("APPDATA")
        base = Path(app_data) if app_data else home / "AppData" / "Roaming"
        return base / "focus" / "focus.db"

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home).expanduser() if xdg_data_home else home / ".local" / "share"
    return base / "focus" / "focus.db"


class FocusStorage:
    """Owns all atomic access to the Focus SQLite database."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else default_database_path()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(self._connect()) as connection:
            connection.executescript(SCHEMA)
            # Databases created before pause support need two additive columns.
            # Keeping the stored status as "active" while paused preserves the
            # existing one-current-session constraint without rebuilding data.
            connection.execute("BEGIN IMMEDIATE")
            try:
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(sessions)")
                }
                if "paused_at" not in columns:
                    connection.execute(
                        "ALTER TABLE sessions ADD COLUMN paused_at REAL NULL"
                    )
                if "paused_seconds" not in columns:
                    connection.execute(
                        "ALTER TABLE sessions ADD COLUMN paused_seconds "
                        "REAL NOT NULL DEFAULT 0"
                    )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        try:
            self.path.chmod(0o600)
        except OSError:
            # Some filesystems (and Windows) do not expose POSIX permissions.
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            timeout=10.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _session(row: sqlite3.Row) -> Session:
        paused_at = row["paused_at"]
        return Session(
            id=row["id"],
            title=row["title"],
            planned_minutes=row["planned_minutes"],
            started_at=row["started_at"],
            planned_end_at=row["planned_end_at"],
            ended_at=row["ended_at"],
            actual_seconds=row["actual_seconds"],
            status=(
                "paused"
                if row["status"] == "active" and paused_at is not None
                else row["status"]
            ),
            base_xp=row["base_xp"],
            bonus_xp=row["bonus_xp"],
            xp_awarded=row["xp_awarded"],
            created_at=row["created_at"],
            paused_at=paused_at,
            paused_seconds=row["paused_seconds"],
        )

    @staticmethod
    def _active_row(connection: sqlite3.Connection) -> Optional[sqlite3.Row]:
        return connection.execute(
            "SELECT * FROM sessions WHERE status = 'active' LIMIT 1"
        ).fetchone()

    @staticmethod
    def _total_xp(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT COALESCE(SUM(xp_awarded), 0) AS total FROM sessions"
        ).fetchone()
        return int(row["total"])

    def total_xp(self) -> int:
        with closing(self._connect()) as connection:
            return self._total_xp(connection)

    def profile_name(self) -> Optional[str]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = 'profile_name'"
            ).fetchone()
            return str(row["value"]) if row is not None else None

    def set_profile_name(self, name: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value) VALUES ('profile_name', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (name,),
            )

    def get_active(self) -> Optional[Session]:
        with closing(self._connect()) as connection:
            row = self._active_row(connection)
            return self._session(row) if row is not None else None

    def get_session(self, session_id: str) -> Optional[Session]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            return self._session(row) if row is not None else None

    def all_sessions(self) -> list[Session]:
        """Return every focus session, newest first."""

        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC"
            ).fetchall()
            return [self._session(row) for row in rows]

    def _finalize_row(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        status: str,
        now: float,
    ) -> FinalizedSession:
        if status == "completed":
            # A completed commitment earns exactly the planned wall-clock time,
            # even if recovery happens much later.
            actual_seconds = int(row["planned_minutes"]) * 60
            ended_at = row["planned_end_at"]
        else:
            effective_now = (
                row["paused_at"] if row["paused_at"] is not None else now
            )
            elapsed = max(
                0.0,
                min(effective_now, row["planned_end_at"])
                - row["started_at"]
                - row["paused_seconds"],
            )
            actual_seconds = int(math.floor(elapsed))
            ended_at = now

        base_xp = actual_seconds // 60
        bonus_xp = math.ceil(base_xp * 0.20) if status == "completed" else 0
        xp_awarded = base_xp + bonus_xp

        connection.execute(
            """
            UPDATE sessions
               SET ended_at = ?, actual_seconds = ?, status = ?,
                   base_xp = ?, bonus_xp = ?, xp_awarded = ?, paused_at = NULL
             WHERE id = ? AND status = 'active'
            """,
            (
                ended_at,
                actual_seconds,
                status,
                base_xp,
                bonus_xp,
                xp_awarded,
                row["id"],
            ),
        )
        finalized_row = connection.execute(
            "SELECT * FROM sessions WHERE id = ?", (row["id"],)
        ).fetchone()
        return FinalizedSession(
            session=self._session(finalized_row),
            total_xp=self._total_xp(connection),
        )

    def recover_expired(self, now: float) -> Optional[FinalizedSession]:
        """Atomically complete an expired active session, if one exists."""

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._active_row(connection)
                if (
                    row is None
                    or row["paused_at"] is not None
                    or now < row["planned_end_at"]
                ):
                    connection.execute("COMMIT")
                    return None
                finalized = self._finalize_row(connection, row, "completed", now)
                connection.execute("COMMIT")
                return finalized
            except BaseException:
                connection.execute("ROLLBACK")
                raise

    def create_session(
        self, planned_minutes: int, title: Optional[str], now: float
    ) -> CreateSessionResult:
        """Create one active session, enforcing the invariant transactionally."""

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                recovered: Optional[FinalizedSession] = None
                row = self._active_row(connection)
                if (
                    row is not None
                    and row["paused_at"] is None
                    and now >= row["planned_end_at"]
                ):
                    recovered = self._finalize_row(connection, row, "completed", now)
                    row = None

                if row is not None:
                    connection.execute("COMMIT")
                    return CreateSessionResult(
                        created=None,
                        existing=self._session(row),
                        recovered=recovered,
                    )

                session_id = str(uuid.uuid4())
                planned_end_at = now + planned_minutes * 60
                connection.execute(
                    """
                    INSERT INTO sessions (
                        id, title, planned_minutes, started_at, planned_end_at,
                        ended_at, actual_seconds, status, base_xp, bonus_xp,
                        xp_awarded, created_at, paused_at, paused_seconds
                    ) VALUES (
                        ?, ?, ?, ?, ?, NULL, NULL, 'active', 0, 0, 0, ?, NULL, 0
                    )
                    """,
                    (
                        session_id,
                        title,
                        planned_minutes,
                        now,
                        planned_end_at,
                        now,
                    ),
                )
                created_row = connection.execute(
                    "SELECT * FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
                connection.execute("COMMIT")
                return CreateSessionResult(
                    created=self._session(created_row),
                    existing=None,
                    recovered=recovered,
                )
            except BaseException:
                connection.execute("ROLLBACK")
                raise

    def stop_active(self, now: float) -> Optional[FinalizedSession]:
        """Atomically stop the active session, or complete it if time is up."""

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._active_row(connection)
                if row is None:
                    connection.execute("COMMIT")
                    return None
                status = (
                    "completed"
                    if row["paused_at"] is None and now >= row["planned_end_at"]
                    else "stopped"
                )
                finalized = self._finalize_row(connection, row, status, now)
                connection.execute("COMMIT")
                return finalized
            except BaseException:
                connection.execute("ROLLBACK")
                raise

    def pause_active(self, now: float) -> PauseSessionResult:
        """Atomically pause the running session without counting paused time."""

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._active_row(connection)
                if row is None:
                    connection.execute("COMMIT")
                    return PauseSessionResult(None, None, None)
                if row["paused_at"] is not None:
                    connection.execute("COMMIT")
                    return PauseSessionResult(None, self._session(row), None)
                if now >= row["planned_end_at"]:
                    completed = self._finalize_row(connection, row, "completed", now)
                    connection.execute("COMMIT")
                    return PauseSessionResult(None, None, completed)

                connection.execute(
                    "UPDATE sessions SET paused_at = ? "
                    "WHERE id = ? AND status = 'active'",
                    (now, row["id"]),
                )
                paused_row = connection.execute(
                    "SELECT * FROM sessions WHERE id = ?", (row["id"],)
                ).fetchone()
                connection.execute("COMMIT")
                return PauseSessionResult(self._session(paused_row), None, None)
            except BaseException:
                connection.execute("ROLLBACK")
                raise

    def resume_paused(self, now: float) -> ResumeSessionResult:
        """Atomically resume the paused session and extend its deadline."""

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._active_row(connection)
                if row is None:
                    connection.execute("COMMIT")
                    return ResumeSessionResult(None, None)
                if row["paused_at"] is None:
                    connection.execute("COMMIT")
                    return ResumeSessionResult(None, self._session(row))

                paused_for = max(0.0, now - row["paused_at"])
                connection.execute(
                    """
                    UPDATE sessions
                       SET planned_end_at = planned_end_at + ?,
                           paused_seconds = paused_seconds + ?, paused_at = NULL
                     WHERE id = ? AND status = 'active'
                    """,
                    (paused_for, paused_for, row["id"]),
                )
                resumed_row = connection.execute(
                    "SELECT * FROM sessions WHERE id = ?", (row["id"],)
                ).fetchone()
                connection.execute("COMMIT")
                return ResumeSessionResult(self._session(resumed_row), None)
            except BaseException:
                connection.execute("ROLLBACK")
                raise

    def complete_session(
        self, session_id: str, now: float
    ) -> Optional[FinalizedSession]:
        """Complete a specific due session without ever double-awarding XP."""

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
                if (
                    row is None
                    or row["status"] != "active"
                    or row["paused_at"] is not None
                    or now < row["planned_end_at"]
                ):
                    connection.execute("COMMIT")
                    return None
                finalized = self._finalize_row(connection, row, "completed", now)
                connection.execute("COMMIT")
                return finalized
            except BaseException:
                connection.execute("ROLLBACK")
                raise
