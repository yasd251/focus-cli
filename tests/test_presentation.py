from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from focus_cli.model import Session
from focus_cli.presentation import (
    TimerDisplay,
    display_title,
    format_clock,
    format_date,
    format_elapsed,
    format_remaining_words,
    format_session_datetime,
    format_time,
    profile_view,
)
from focus_cli.storage import FocusStorage


class PresentationTests(unittest.TestCase):
    class TtyBuffer(io.StringIO):
        def isatty(self) -> bool:
            return True

    def test_clock_formats(self) -> None:
        self.assertEqual(format_clock(59 * 60 + 42), "59:42")
        self.assertEqual(format_clock(100 * 60, show_hours=True), "01:40:00")
        self.assertEqual(format_clock(0), "00:00")

    def test_human_duration_formats(self) -> None:
        self.assertEqual(format_elapsed(37 * 60 + 24), "37m 24s")
        self.assertEqual(format_elapsed(60 * 60), "60m")
        self.assertEqual(format_elapsed(24), "24s")
        self.assertEqual(format_remaining_words(2 * 3600 + 18), "2h 0m 18s")

    def test_date_has_readable_long_form(self) -> None:
        self.assertRegex(format_date(100), r"^[A-Z][a-z]+, [A-Z][a-z]+ \d{1,2}, 1970$")

    def test_session_datetime_uses_day_month_and_lowercase_meridiem(self) -> None:
        rendered = format_session_datetime(100)
        self.assertRegex(
            rendered,
            r"^[A-Z][a-z]+, \d{1,2} [A-Z][a-z]+ \d{4}, \d{1,2}:\d{2} (am|pm)$",
        )

    def test_missing_title_has_display_fallback(self) -> None:
        self.assertEqual(display_title(None), "No description")

    def test_empty_profile_has_xp_and_no_extra_statistics(self) -> None:
        rendered = profile_view([], 0, 100, width=80)
        self.assertNotIn("│  │ F │  │", rendered)
        self.assertIn("0 XP", rendered)
        self.assertIn("No focus sessions yet.", rendered)
        self.assertNotIn("Total focus", rendered)

    def test_profile_renders_configured_name_above_xp(self) -> None:
        rendered = profile_view([], 42, 100, name="Lemuel", width=80)
        self.assertTrue(rendered.startswith("Hey, Lemuel\nTotal XP: 42 XP\n"))

    def test_live_input_preserves_characters_and_handles_backspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = FocusStorage(Path(directory) / "focus.db")
            storage.initialize()
            session = storage.create_session(25, None, 100).created
            output = io.StringIO()
            display = TimerDisplay(
                storage,
                session,
                stdin=io.StringIO(),
                stdout=output,
            )

            for character in "focus stqp\x7f\x7fop":
                display._commands.put(character)
            self.assertIsNone(display._read_command())
            self.assertEqual(display._input_buffer, "focus stop")

            display._render(100)
            self.assertIn("> focus stop", output.getvalue())

            display._commands.put("\n")
            self.assertEqual(display._read_command(), "focus stop")
            self.assertEqual(display._input_buffer, "")

    def test_live_layout_is_centered_minimal_and_red_accented(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = FocusStorage(Path(directory) / "focus.db")
            storage.initialize()
            previous = storage.create_session(10, "Previous work", -1_000).created
            storage.complete_session(previous.id, -400)
            session = storage.create_session(25, "Write the report", 100).created
            output = self.TtyBuffer()
            display = TimerDisplay(
                storage,
                session,
                stdin=self.TtyBuffer(),
                stdout=output,
            )
            display._input_buffer = "focus stop"

            display._render(400)
            rendered = output.getvalue()

            self.assertIn("\x1b[38;2;239;68;68m", rendered)
            self.assertIn("\x1b[38;2;251;191;36m", rendered)
            self.assertIn("\x1b[38;2;148;163;184m", rendered)
            self.assertIn("\x1b[38;2;34;197;94m", rendered)
            self.assertIn("╭", rendered)
            self.assertIn("You currently have a total of 12 XP", rendered)
            self.assertIn(
                "Finishing this focus session will give you +30 XP", rendered
            )
            self.assertIn("20:00", rendered)
            self.assertIn("focus stop", rendered)
            self.assertIn(format_date(session.started_at), rendered)
            self.assertIn(f"Started {format_time(session.started_at)}", rendered)
            self.assertNotIn("│  F  │", rendered)
            self.assertNotIn("\x1b[38;2;248;113;113m", rendered)
            self.assertNotIn("\x1b[38;2;153;27;27m", rendered)
            self.assertLess(rendered.index("Write the report"), rendered.index("1970"))
            self.assertNotIn("FOCUS SESSION", rendered)
            self.assertNotIn("✓", rendered)

    def test_live_resize_clears_previous_frame_before_painting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = FocusStorage(Path(directory) / "focus.db")
            storage.initialize()
            session = storage.create_session(25, "Resize safely", 100).created
            output = self.TtyBuffer()
            display = TimerDisplay(
                storage,
                session,
                stdin=self.TtyBuffer(),
                stdout=output,
            )

            sizes = [os.terminal_size((80, 24)), os.terminal_size((52, 18))]
            with patch(
                "focus_cli.presentation.shutil.get_terminal_size",
                side_effect=sizes,
            ):
                display._render(100)
                first_frame_length = len(output.getvalue())
                display._render(101)
            second_frame = output.getvalue()[first_frame_length:]

            self.assertTrue(second_frame.startswith("\x1b[?25l\x1b[2J\x1b[H"))
            self.assertLess(second_frame.index("\x1b[2J"), second_frame.index("24:59"))

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

    def test_noninteractive_start_describes_total_and_completion_xp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = FocusStorage(Path(directory) / "focus.db")
            storage.initialize()
            previous = storage.create_session(10, "Previous", -1_000).created
            storage.complete_session(previous.id, -400)
            session = storage.create_session(25, "Current", 100).created
            output = io.StringIO()

            def interrupted_time():
                raise KeyboardInterrupt

            display = TimerDisplay(
                storage,
                session,
                stdin=io.StringIO(),
                stdout=output,
                now=interrupted_time,
            )

            self.assertIsNone(display.run())
            self.assertIn(
                "You currently have a total of 12 XP\n", output.getvalue()
            )
            self.assertIn(
                "Finishing this focus session will give you +30 XP\n",
                output.getvalue(),
            )
            self.assertNotIn("\x1b[", output.getvalue())

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

    def test_timer_exits_cleanly_when_session_is_deleted_elsewhere(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = FocusStorage(Path(directory) / "focus.db")
            storage.initialize()
            session = storage.create_session(25, "Delete me", 100).created
            storage.delete_latest()

            display = TimerDisplay(
                storage,
                session,
                stdin=io.StringIO(),
                stdout=io.StringIO(),
                now=lambda: 101,
                tick_seconds=0.001,
            )

            self.assertIsNone(display.run())

    def test_live_pause_command_pauses_and_returns_the_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = FocusStorage(Path(directory) / "focus.db")
            storage.initialize()
            session = storage.create_session(25, "Pause me", 100).created
            display = TimerDisplay(
                storage,
                session,
                stdin=io.StringIO(),
                stdout=io.StringIO(),
                now=lambda: 220,
                tick_seconds=0.001,
            )
            for character in "focus pause\n":
                display._commands.put(character)

            result = display.run()

            self.assertEqual(result.status, "paused")
            self.assertEqual(result.focused_seconds_at(10_000), 120)
            self.assertEqual(storage.get_active().status, "paused")

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
                tick_seconds=0.001,
            )

            result = display.run()

            self.assertEqual(result.session.status, "completed")
            self.assertEqual(result.session.actual_seconds, 60)
            self.assertEqual(result.session.xp_awarded, 2)


if __name__ == "__main__":
    unittest.main()
