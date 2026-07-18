from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from focus_cli.storage import FocusStorage


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "nested" / "focus.db"
        self.storage = FocusStorage(self.path)
        self.storage.initialize()

    def test_create_persists_all_active_session_fields(self) -> None:
        result = self.storage.create_session(60, "Math Möbius", 1_000.25)

        self.assertIsNotNone(result.created)
        session = result.created
        self.assertEqual(session.title, "Math Möbius")
        self.assertEqual(session.planned_minutes, 60)
        self.assertEqual(session.started_at, 1_000.25)
        self.assertEqual(session.planned_end_at, 4_600.25)
        self.assertEqual(session.status, "active")
        self.assertIsNone(session.actual_seconds)
        self.assertEqual(session.xp_awarded, 0)
        self.assertEqual(self.storage.get_active().id, session.id)

    def test_second_session_is_not_created(self) -> None:
        first = self.storage.create_session(60, None, 100).created
        result = self.storage.create_session(25, "second", 101)

        self.assertIsNone(result.created)
        self.assertEqual(result.existing.id, first.id)
        self.assertEqual(len(self.storage.all_sessions()), 1)

    def test_stopped_session_uses_floor_minutes_and_no_bonus(self) -> None:
        self.storage.create_session(60, "Work", 100)
        result = self.storage.stop_active(100 + 37 * 60 + 24.9)

        self.assertEqual(result.session.status, "stopped")
        self.assertEqual(result.session.actual_seconds, 37 * 60 + 24)
        self.assertEqual(result.session.base_xp, 37)
        self.assertEqual(result.session.bonus_xp, 0)
        self.assertEqual(result.session.xp_awarded, 37)
        self.assertEqual(result.total_xp, 37)
        self.assertIsNone(self.storage.get_active())

    def test_short_stopped_session_earns_zero_xp(self) -> None:
        self.storage.create_session(10, None, 100)
        result = self.storage.stop_active(159.99)
        self.assertEqual(result.session.actual_seconds, 59)
        self.assertEqual(result.session.xp_awarded, 0)

    def test_completed_session_gets_twenty_percent_ceiling_bonus(self) -> None:
        created = self.storage.create_session(25, None, 100).created
        result = self.storage.complete_session(created.id, 1_600)

        self.assertEqual(result.session.status, "completed")
        self.assertEqual(result.session.actual_seconds, 1_500)
        self.assertEqual(result.session.ended_at, 1_600)
        self.assertEqual(result.session.base_xp, 25)
        self.assertEqual(result.session.bonus_xp, 5)
        self.assertEqual(result.session.xp_awarded, 30)

    def test_recovery_completes_only_after_deadline_and_awards_once(self) -> None:
        created = self.storage.create_session(10, None, 100).created
        self.assertIsNone(self.storage.recover_expired(699.999))

        recovered = self.storage.recover_expired(900)
        recovered_again = self.storage.recover_expired(901)
        completed_again = self.storage.complete_session(created.id, 902)

        self.assertEqual(recovered.session.status, "completed")
        self.assertEqual(recovered.session.ended_at, 700)
        self.assertEqual(recovered.session.actual_seconds, 600)
        self.assertEqual(recovered.session.xp_awarded, 12)
        self.assertEqual(recovered.total_xp, 12)
        self.assertIsNone(recovered_again)
        self.assertIsNone(completed_again)
        self.assertEqual(self.storage.total_xp(), 12)

    def test_create_atomically_recovers_expired_session_then_starts_new_one(self) -> None:
        old = self.storage.create_session(1, "old", 100).created
        result = self.storage.create_session(25, "new", 161)

        self.assertEqual(result.recovered.session.id, old.id)
        self.assertEqual(result.recovered.session.xp_awarded, 2)
        self.assertEqual(result.created.title, "new")
        self.assertEqual(result.created.status, "active")
        self.assertEqual(len(self.storage.all_sessions()), 2)

    def test_stop_at_or_after_deadline_counts_as_completion(self) -> None:
        self.storage.create_session(1, None, 100)
        result = self.storage.stop_active(160)
        self.assertEqual(result.session.status, "completed")
        self.assertEqual(result.session.xp_awarded, 2)

    def test_pause_freezes_remaining_time_and_resume_extends_deadline(self) -> None:
        created = self.storage.create_session(10, "Deep work", 100).created

        paused = self.storage.pause_active(220)
        session = paused.paused

        self.assertEqual(session.status, "paused")
        self.assertEqual(session.focused_seconds_at(500), 120)
        self.assertEqual(session.remaining_seconds_at(500), 480)
        self.assertIsNone(self.storage.recover_expired(10_000))
        self.assertEqual(self.storage.total_xp(), 0)

        resumed = self.storage.resume_paused(500).resumed
        self.assertEqual(resumed.status, "active")
        self.assertEqual(resumed.planned_end_at, created.planned_end_at + 280)
        self.assertEqual(resumed.paused_seconds, 280)
        self.assertEqual(resumed.focused_seconds_at(500), 120)

    def test_repeated_pauses_are_excluded_from_stopped_session_xp(self) -> None:
        self.storage.create_session(10, None, 100)
        self.storage.pause_active(220)
        self.storage.resume_paused(520)
        self.storage.pause_active(640)
        self.storage.resume_paused(700)

        result = self.storage.stop_active(820)

        self.assertEqual(result.session.status, "stopped")
        self.assertEqual(result.session.actual_seconds, 360)
        self.assertEqual(result.session.xp_awarded, 6)

    def test_stopping_a_paused_session_never_counts_the_break_as_completion(self) -> None:
        self.storage.create_session(1, None, 100)
        self.storage.pause_active(120)

        result = self.storage.stop_active(1_000)

        self.assertEqual(result.session.status, "stopped")
        self.assertEqual(result.session.actual_seconds, 20)
        self.assertEqual(result.session.xp_awarded, 0)

    def test_resumed_session_completes_at_extended_deadline(self) -> None:
        created = self.storage.create_session(1, None, 100).created
        self.storage.pause_active(120)
        resumed = self.storage.resume_paused(1_000).resumed

        self.assertEqual(resumed.planned_end_at, created.planned_end_at + 880)
        self.assertIsNone(self.storage.complete_session(created.id, 1_039.9))
        completed = self.storage.complete_session(created.id, 1_040)
        self.assertEqual(completed.session.status, "completed")
        self.assertEqual(completed.session.xp_awarded, 2)

    def test_initialize_upgrades_database_created_before_pause_support(self) -> None:
        old_path = Path(self.temp_dir.name) / "old.db"
        with sqlite3.connect(old_path) as connection:
            connection.execute(
                """
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY, title TEXT NULL,
                    planned_minutes INTEGER NOT NULL, started_at REAL NOT NULL,
                    planned_end_at REAL NOT NULL, ended_at REAL NULL,
                    actual_seconds INTEGER NULL, status TEXT NOT NULL,
                    base_xp INTEGER NOT NULL DEFAULT 0,
                    bonus_xp INTEGER NOT NULL DEFAULT 0,
                    xp_awarded INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO sessions VALUES "
                "('old', 'Existing', 10, 100, 700, NULL, NULL, "
                "'active', 0, 0, 0, 100)"
            )

        upgraded = FocusStorage(old_path)
        upgraded.initialize()

        session = upgraded.get_active()
        self.assertEqual(session.id, "old")
        self.assertIsNone(session.paused_at)
        self.assertEqual(session.paused_seconds, 0)
        self.assertEqual(upgraded.pause_active(200).paused.status, "paused")

    def test_database_enforces_only_one_active_row(self) -> None:
        self.storage.create_session(10, None, 100)
        with sqlite3.connect(self.path) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO sessions (
                      id, title, planned_minutes, started_at, planned_end_at,
                      ended_at, actual_seconds, status, base_xp, bonus_xp,
                      xp_awarded, created_at
                    ) VALUES (
                      'other', NULL, 10, 100, 700, NULL, NULL,
                      'active', 0, 0, 0, 100
                    )
                    """
                )

    def test_simultaneous_starts_create_exactly_one_active_session(self) -> None:
        barrier = threading.Barrier(3)
        results = []
        errors = []

        def create(title: str) -> None:
            try:
                storage = FocusStorage(self.path)
                barrier.wait()
                results.append(storage.create_session(25, title, 100))
            except BaseException as error:  # make thread failures visible
                errors.append(error)

        threads = [
            threading.Thread(target=create, args=("one",)),
            threading.Thread(target=create, args=("two",)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(sum(result.created is not None for result in results), 1)
        self.assertEqual(sum(result.existing is not None for result in results), 1)
        self.assertEqual(len(self.storage.all_sessions()), 1)


if __name__ == "__main__":
    unittest.main()
