from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from focus_cli import cli
from focus_cli.presentation import format_session_datetime
from focus_cli.storage import FocusStorage


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "focus.db"

    def run_cli(self, arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = cli.main(
            arguments,
            stdin=io.StringIO(),
            stdout=stdout,
            stderr=stderr,
            database_path=self.path,
        )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_help_matches_public_commands(self) -> None:
        code, stdout, stderr = self.run_cli(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("focus start <minutes> [options]", stdout)
        self.assertIn("focus pause", stdout)
        self.assertIn("focus resume", stdout)
        self.assertIn("focus stop", stdout)
        self.assertIn("focus profile", stdout)
        self.assertIn("focus delete latest", stdout)
        self.assertIn("focus config name <name>", stdout)
        self.assertIn("--title", stdout)
        self.assertEqual(stderr, "")

    def test_unknown_command_exits_two(self) -> None:
        code, stdout, stderr = self.run_cli(["history"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("Unknown command: history", stderr)

    def test_stop_arguments_exit_two(self) -> None:
        code, _, stderr = self.run_cli(["stop", "now"])
        self.assertEqual(code, 2)
        self.assertIn("does not accept arguments", stderr)

    def test_profile_arguments_exit_two(self) -> None:
        code, _, stderr = self.run_cli(["profile", "extra"])
        self.assertEqual(code, 2)
        self.assertIn("profile command does not accept arguments", stderr)

    def test_config_requires_a_valid_name(self) -> None:
        invalid_arguments = [
            ["config"],
            ["config", "color", "red"],
            ["config", "name", "   "],
            ["config", "name", "x" * 81],
            ["config", "name", "First\nLast"],
        ]
        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                code, stdout, stderr = self.run_cli(arguments)
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertIn("focus config name <name>", stderr)

    def test_pause_and_resume_arguments_exit_two(self) -> None:
        for command in ("pause", "resume"):
            with self.subTest(command=command):
                code, _, stderr = self.run_cli([command, "now"])
                self.assertEqual(code, 2)
                self.assertIn("does not accept arguments", stderr)

    def test_delete_requires_latest(self) -> None:
        invalid = [
            ["delete"],
            ["delete", "oldest"],
            ["delete", "latest", "now"],
        ]
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                code, stdout, stderr = self.run_cli(arguments)
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertIn("only supports `latest`", stderr)
                self.assertIn("focus delete latest", stderr)

    def test_duration_validation(self) -> None:
        invalid = ["zero", "-20", "0", "1.5", "60m", "1441"]
        for value in invalid:
            with self.subTest(value=value):
                error = io.StringIO()
                with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                    cli.start_parser().parse_args([value])
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("between 1 and 1440 minutes", error.getvalue())

        self.assertEqual(cli.start_parser().parse_args(["1"]).minutes, 1)
        self.assertEqual(cli.start_parser().parse_args(["1440"]).minutes, 1440)

    def test_missing_duration_has_the_duration_error(self) -> None:
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            cli.start_parser().parse_args([])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("between 1 and 1440 minutes", error.getvalue())

    def test_title_is_trimmed_and_limited(self) -> None:
        parsed = cli.start_parser().parse_args(["25", "-t", "  Write!  "])
        self.assertEqual(parsed.title, "Write!")
        parsed = cli.start_parser().parse_args(["25", "--title", "   "])
        self.assertIsNone(parsed.title)

        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit):
            cli.start_parser().parse_args(["25", "-t", "x" * 201])
        self.assertIn("200 characters or fewer", error.getvalue())

    def test_stop_without_active_session_is_informational(self) -> None:
        code, stdout, stderr = self.run_cli(["stop"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "No focus session is currently active.\n")
        self.assertEqual(stderr, "")

    def test_pause_and_resume_without_a_session_are_informational(self) -> None:
        code, stdout, stderr = self.run_cli(["pause"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "No focus session is currently active.\n")
        self.assertEqual(stderr, "")

        code, stdout, stderr = self.run_cli(["resume"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "No paused focus session to resume.\n")
        self.assertEqual(stderr, "")

    def test_delete_latest_without_sessions_is_informational(self) -> None:
        code, stdout, stderr = self.run_cli(["delete", "latest"])

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "No focus sessions to delete.\n")
        self.assertEqual(stderr, "")

    def test_delete_latest_reports_and_removes_newest_session(self) -> None:
        storage = FocusStorage(self.path)
        storage.initialize()
        older = storage.create_session(10, "Older work", 100).created
        storage.complete_session(older.id, 700)
        storage.create_session(5, "Accidental work", 800)
        storage.stop_active(920)

        code, stdout, stderr = self.run_cli(["delete", "latest"])

        self.assertEqual(code, 0)
        self.assertIn("Deleted latest focus session permanently.", stdout)
        self.assertIn("Title:   Accidental work", stdout)
        self.assertIn("Status:  STOPPED", stdout)
        self.assertEqual(stderr, "")
        self.assertEqual(
            [session.id for session in storage.all_sessions()], [older.id]
        )
        self.assertEqual(storage.total_xp(), 12)

    def test_pause_then_resume_preserves_the_countdown(self) -> None:
        storage = FocusStorage(self.path)
        storage.initialize()
        created = storage.create_session(25, "Write report", 100).created

        with patch("focus_cli.cli.time.time", return_value=220):
            code, stdout, stderr = self.run_cli(["pause"])

        self.assertEqual(code, 0)
        self.assertIn("Focus session paused.", stdout)
        self.assertIn("Focused for: 2m", stdout)
        self.assertIn("Remaining:   23m 0s", stdout)
        self.assertIn("focus resume", stdout)
        self.assertEqual(stderr, "")
        self.assertEqual(storage.get_active().status, "paused")

        with patch("focus_cli.cli.time.time", return_value=520):
            with patch.object(cli.TimerDisplay, "run", return_value=None):
                code, stdout, stderr = self.run_cli(["resume"])

        resumed = storage.get_active()
        self.assertEqual(code, 0)
        self.assertIn("Timer display closed", stdout)
        self.assertEqual(stderr, "")
        self.assertEqual(resumed.status, "active")
        self.assertEqual(resumed.planned_end_at, created.planned_end_at + 300)
        self.assertEqual(resumed.focused_seconds_at(520), 120)

    def test_profile_shows_paused_session_without_recovering_it(self) -> None:
        storage = FocusStorage(self.path)
        storage.initialize()
        storage.create_session(1, "Paused work", 100)
        storage.pause_active(120)

        with patch("focus_cli.cli.time.time", return_value=10_000):
            code, stdout, stderr = self.run_cli(["profile"])

        self.assertEqual(code, 0)
        self.assertIn("PAUSED", stdout)
        self.assertIn("20s / 1m", stdout)
        self.assertNotIn("Recovered completed session", stdout)
        self.assertEqual(stderr, "")

    def test_configured_name_is_trimmed_and_shown_with_profile_xp(self) -> None:
        code, stdout, stderr = self.run_cli(
            ["config", "name", "  Lemuel  "]
        )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "Profile name set to Lemuel.\n")
        self.assertEqual(stderr, "")

        code, stdout, stderr = self.run_cli(["profile"])

        self.assertEqual(code, 0)
        self.assertIn("Hey, Lemuel\nTotal XP: 0 XP", stdout)
        self.assertEqual(stderr, "")

    def test_start_persists_before_display_and_ctrl_c_style_close_keeps_active(self) -> None:
        with patch.object(cli.TimerDisplay, "run", return_value=None):
            code, stdout, stderr = self.run_cli(
                ["start", "60", "-t", "  Math Möbius  "]
            )

        self.assertEqual(code, 0)
        self.assertIn("Timer display closed", stdout)
        self.assertEqual(stderr, "")
        active = FocusStorage(self.path).get_active()
        self.assertEqual(active.title, "Math Möbius")
        self.assertEqual(active.planned_minutes, 60)

    def test_second_start_reports_existing_session_without_new_record(self) -> None:
        storage = FocusStorage(self.path)
        storage.initialize()
        storage.create_session(60, "Existing", 10_000_000_000)

        code, stdout, stderr = self.run_cli(["start", "25"])

        self.assertEqual(code, 0)
        self.assertIn("already running", stdout)
        self.assertIn("Title: Existing", stdout)
        self.assertIn("focus stop", stdout)
        self.assertEqual(stderr, "")
        self.assertEqual(len(storage.all_sessions()), 1)

    def test_stop_prints_summary_and_total_xp(self) -> None:
        storage = FocusStorage(self.path)
        storage.initialize()
        with patch("focus_cli.cli.time.time", return_value=100):
            with patch.object(cli.TimerDisplay, "run", return_value=None):
                self.run_cli(["start", "60", "-t", "Work"])

        with patch("focus_cli.cli.time.time", return_value=100 + 37 * 60 + 24):
            code, stdout, stderr = self.run_cli(["stop"])

        self.assertEqual(code, 0)
        self.assertIn("Session stopped.", stdout)
        self.assertIn("Focused for: 37m 24s", stdout)
        self.assertIn("Planned:     60m", stdout)
        self.assertIn("XP earned:   +37 XP", stdout)
        self.assertIn("Total XP:    37 XP", stdout)
        self.assertIn("Work", stdout)
        self.assertEqual(stderr, "")

    def test_expired_session_is_reported_as_recovered_completion(self) -> None:
        storage = FocusStorage(self.path)
        storage.initialize()
        storage.create_session(1, "Recovered work", 100)

        with patch("focus_cli.cli.time.time", return_value=200):
            code, stdout, stderr = self.run_cli(["stop"])

        self.assertEqual(code, 0)
        self.assertIn("Recovered completed session.", stdout)
        self.assertIn("Focused for: 1m", stdout)
        self.assertIn("XP earned:   +2 XP", stdout)
        self.assertIn("Recovered work", stdout)
        self.assertEqual(stderr, "")

    def test_profile_shows_xp_and_every_session_status(self) -> None:
        storage = FocusStorage(self.path)
        storage.initialize()

        completed = storage.create_session(10, "Finished work", 100).created
        storage.complete_session(completed.id, 700)
        storage.create_session(10, "Stopped work", 800)
        storage.stop_active(920)
        storage.create_session(25, "Current work", 1_000)

        with patch("focus_cli.cli.time.time", return_value=1_010):
            code, stdout, stderr = self.run_cli(["profile"])

        self.assertEqual(code, 0)
        self.assertNotIn("│  │ F │  │", stdout)
        self.assertIn("14 XP", stdout)
        self.assertIn("ACTIVE", stdout)
        self.assertIn("COMPLETED", stdout)
        self.assertIn("STOPPED", stdout)
        self.assertIn("Current work", stdout)
        self.assertIn("Finished work", stdout)
        self.assertIn("Stopped work", stdout)
        self.assertIn(f"Started: {format_session_datetime(1_000)}", stdout)
        self.assertIn(f"Started: {format_session_datetime(800)}", stdout)
        self.assertIn(f"Started: {format_session_datetime(100)}", stdout)
        self.assertNotIn("Total focus", stdout)
        self.assertNotIn("Sessions completed", stdout)
        self.assertEqual(stderr, "")

    def test_profile_recovers_expired_session_before_counting_xp(self) -> None:
        storage = FocusStorage(self.path)
        storage.initialize()
        storage.create_session(1, "Due work", 100)

        with patch("focus_cli.cli.time.time", return_value=200):
            code, stdout, _ = self.run_cli(["profile"])

        self.assertEqual(code, 0)
        self.assertIn("Recovered completed session.", stdout)
        self.assertIn("2 XP", stdout)
        self.assertIn("COMPLETED", stdout)

    def test_storage_failure_exits_one_with_actionable_path(self) -> None:
        impossible_path = self.path / "directory-is-file" / "focus.db"
        self.path.write_text("not a directory")
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = cli.main(
            ["stop"],
            stdout=stdout,
            stderr=stderr,
            database_path=impossible_path,
        )
        self.assertEqual(code, 1)
        self.assertIn("could not access its local database", stderr.getvalue())
        self.assertIn(str(impossible_path), stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
