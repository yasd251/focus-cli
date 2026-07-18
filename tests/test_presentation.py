from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from focus_cli.model import Session
from focus_cli.presentation import (
    TimerDisplay,
    display_title,
    format_clock,
    format_elapsed,
    format_remaining_words,
)
from focus_cli.storage import FocusStorage


class PresentationTests(unittest.TestCase):
    def test_clock_formats(self) -> None:
        self.assertEqual(format_clock(59 * 60 + 42), "59:42")
        self.assertEqual(format_clock(100 * 60, show_hours=True), "01:40:00")
        self.assertEqual(format_clock(0), "00:00")

    def test_human_duration_formats(self) -> None:
        self.assertEqual(format_elapsed(37 * 60 + 24), "37m 24s")
        self.assertEqual(format_elapsed(60 * 60), "60m")
        self.assertEqual(format_elapsed(24), "24s")
        self.assertEqual(format_remaining_words(2 * 3600 + 18), "2h 0m 18s")

    def test_missing_title_has_display_fallback(self) -> None:
        self.assertEqual(display_title(None), "No description")

    def test_keyboard_interrupt_closes_display_but_keeps_session_active(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = FocusStorage(Path(directory) / "focus.db")
            storage.initialize()
            session = storage.create_session(25, None, 100).created

            def interrupted_time():
                raise KeyboardInterrupt

            output = io.StringIO()
            display = TimerDisplay(
                storage,
                session,
                stdin=io.StringIO(),
                stdout=output,
                now=interrupted_time,
                tick_seconds=0.001,
            )
            self.assertIsNone(display.run())
            self.assertEqual(storage.get_active().id, session.id)

    def test_timer_detects_session_stopped_elsewhere_without_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = FocusStorage(Path(directory) / "focus.db")
            storage.initialize()
            session = storage.create_session(25, "Cross terminal", 100).created
            stopped = storage.stop_active(220)

            display = TimerDisplay(
                storage,
                session,
                stdin=io.StringIO(),
                stdout=io.StringIO(),
                now=lambda: 221,
                tick_seconds=0.001,
            )
            result = display.run()
            self.assertEqual(result.session.id, stopped.session.id)
            self.assertEqual(result.session.status, "stopped")
            self.assertEqual(result.session.xp_awarded, 2)

    def test_timer_uses_wall_clock_jump_to_complete_without_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = FocusStorage(Path(directory) / "focus.db")
            storage.initialize()
            session = storage.create_session(1, "Clock jump", 100).created
            times = iter([100, 101, 200])
            display = TimerDisplay(
                storage,
                session,
                stdin=io.StringIO(),
                stdout=io.StringIO(),
                now=lambda: next(times),
                tick_seconds=1,
            )

            with patch("focus_cli.presentation.time.sleep", return_value=None):
                result = display.run()

            self.assertEqual(result.session.status, "completed")
            self.assertEqual(result.session.actual_seconds, 60)
            self.assertEqual(result.session.xp_awarded, 2)


if __name__ == "__main__":
    unittest.main()
