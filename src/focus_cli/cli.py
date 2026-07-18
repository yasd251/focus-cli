"""Command-line interface for Focus CLI."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional, Sequence, TextIO

from .model import FinalizedSession, Session
from .presentation import (
    TimerDisplay,
    display_title,
    final_summary,
    format_remaining_words,
    pause_summary,
    profile_view,
)
from .storage import FocusStorage, default_database_path


HELP = r"""
  .-.                                               
 /    \                                             
 | .`. ;    .--.     .--.     ___  ___      .--.    
 | |(___)  /    \   /    \   (   )(   )   /  _  \   
 | |_     |  .-. ; |  .-. ;   | |  | |   . .' `. ;  
(   __)   | |  | | |  |(___)  | |  | |   | '   | |  
 | |      | |  | | |  |       | |  | |   _\_`.(___) 
 | |      | |  | | |  | ___   | |  | |  (   ). '.   
 | |      | '  | | |  '(   )  | |  ; '   | |  `\ |  
 | |      '  `-' / '  `-' |   ' `-'  /   ; '._,' '  
(___)      `.__.'   `.__,'     '.__.'     '.___.'                                                              

A minimal focus timer that rewards completed sessions with XP.

Usage:
  focus start <minutes> [options]
  focus pause
  focus resume
  focus stop
  focus profile

Commands:
  start    Start a focus session
  pause    Pause the active focus session
  resume   Resume the paused focus session
  stop     Stop the active focus session
  profile  Show your XP and all focus sessions

Start options:
  -t, --title <text>    Describe what you are focusing on
  -h, --help            Show command help

Examples:
  focus start 25
  focus start 60 -t "Working on Math Möbius"
  focus pause
  focus resume
  focus stop
  focus profile
"""

START_USAGE = 'Usage:\n  focus start <minutes> [-t "description"]'


class FocusArgumentParser(argparse.ArgumentParser):
    def __init__(
        self,
        *args,
        stdout: Optional[TextIO] = None,
        stderr: Optional[TextIO] = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._stdout = stdout
        self._stderr = stderr

    def _print_message(self, message: str, file: Optional[TextIO] = None) -> None:
        if message:
            if file is sys.stderr and self._stderr is not None:
                file = self._stderr
            elif file is sys.stdout and self._stdout is not None:
                file = self._stdout
            super()._print_message(message, file)

    def error(self, message: str) -> None:
        if message == "the following arguments are required: minutes":
            message = "Duration must be between 1 and 1440 minutes."
        message = re.sub(r"^argument minutes: ", "", message)
        message = re.sub(r"^argument -t/--title: ", "", message)
        self.exit(2, f"Error: {message}\n\n{START_USAGE}\n")


def duration(value: str) -> int:
    if not re.fullmatch(r"[0-9]+", value):
        raise argparse.ArgumentTypeError(
            "Duration must be between 1 and 1440 minutes."
        )
    parsed = int(value)
    if parsed < 1 or parsed > 1440:
        raise argparse.ArgumentTypeError(
            "Duration must be between 1 and 1440 minutes."
        )
    return parsed


def title(value: str) -> Optional[str]:
    trimmed = value.strip()
    if len(trimmed) > 200:
        raise argparse.ArgumentTypeError("Title must be 200 characters or fewer.")
    return trimmed or None


def start_parser(
    *, stdout: Optional[TextIO] = None, stderr: Optional[TextIO] = None
) -> FocusArgumentParser:
    parser = FocusArgumentParser(
        prog="focus start",
        add_help=False,
        description="Start a focus session.",
        stdout=stdout,
        stderr=stderr,
    )
    parser.add_argument("minutes", type=duration)
    parser.add_argument("-t", "--title", dest="title", type=title)
    parser.add_argument("-h", "--help", action="help", help="Show command help")
    return parser


def _print_recovered(recovered: FinalizedSession, stdout: TextIO) -> None:
    stdout.write(final_summary(recovered, recovered=True) + "\n\n")


def _print_current_session(session: Session, stdout: TextIO, now: float) -> None:
    if session.status == "paused":
        stdout.write(pause_summary(session, now, already_paused=True) + "\n")
        return
    stdout.write(
        "A focus session is already running.\n\n"
        f"Remaining: {format_remaining_words(session.remaining_seconds_at(now))}\n"
        f"Title: {display_title(session.title)}\n\n"
        "Use `focus pause` to pause it or `focus stop` to end it.\n"
    )


def _display_session(
    storage: FocusStorage,
    session: Session,
    *,
    stdin: TextIO,
    stdout: TextIO,
) -> int:
    result = TimerDisplay(
        storage,
        session,
        stdin=stdin,
        stdout=stdout,
    ).run()
    if result is None:
        stdout.write(
            "Timer display closed. Your focus session is still running.\n\n"
            "Run `focus pause` to pause it or `focus stop` to stop it.\n"
        )
        return 0

    result_session = (
        result.session if isinstance(result, FinalizedSession) else result
    )
    if result_session.status == "paused":
        stdout.write(pause_summary(result_session, time.time()) + "\n")
        return 0

    if result.session.status == "completed" and getattr(
        stdout, "isatty", lambda: False
    )():
        stdout.write("\a")
    stdout.write(final_summary(result) + "\n")
    return 0


def _run_start(
    options: argparse.Namespace,
    storage: FocusStorage,
    *,
    stdin: TextIO,
    stdout: TextIO,
) -> int:
    result = storage.create_session(options.minutes, options.title, time.time())

    if result.recovered is not None:
        _print_recovered(result.recovered, stdout)

    if result.existing is not None:
        _print_current_session(result.existing, stdout, time.time())
        return 0

    if result.created is None:
        raise RuntimeError("Focus could not create the session.")

    return _display_session(storage, result.created, stdin=stdin, stdout=stdout)


def _run_pause(storage: FocusStorage, stdout: TextIO) -> int:
    now = time.time()
    result = storage.pause_active(now)
    if result.completed is not None:
        stdout.write(final_summary(result.completed, recovered=True) + "\n")
    elif result.paused is not None:
        stdout.write(pause_summary(result.paused, now) + "\n")
    elif result.existing is not None:
        stdout.write(
            pause_summary(result.existing, now, already_paused=True) + "\n"
        )
    else:
        stdout.write("No focus session is currently active.\n")
    return 0


def _run_resume(
    storage: FocusStorage,
    *,
    stdin: TextIO,
    stdout: TextIO,
) -> int:
    now = time.time()
    result = storage.resume_paused(now)
    if result.existing is not None:
        _print_current_session(result.existing, stdout, now)
        return 0
    if result.resumed is None:
        stdout.write("No paused focus session to resume.\n")
        return 0
    return _display_session(storage, result.resumed, stdin=stdin, stdout=stdout)


def _run_stop(storage: FocusStorage, stdout: TextIO) -> int:
    finalized = storage.stop_active(time.time())
    if finalized is None:
        stdout.write("No focus session is currently active.\n")
        return 0
    # Reaching the deadline is completion, even when the command that notices
    # it happens to be `focus stop`.
    stdout.write(
        final_summary(finalized, recovered=finalized.session.status == "completed")
        + "\n"
    )
    return 0


def _run_profile(storage: FocusStorage, stdout: TextIO) -> int:
    now = time.time()
    recovered = storage.recover_expired(now)
    if recovered is not None:
        _print_recovered(recovered, stdout)
    sessions = storage.all_sessions()
    interactive = bool(getattr(stdout, "isatty", lambda: False)())
    stdout.write(
        profile_view(
            sessions,
            storage.total_xp(),
            now,
            interactive=interactive,
        )
    )
    return 0


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    stdin: Optional[TextIO] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
    database_path: Optional[Path] = None,
) -> int:
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    arguments = list(sys.argv[1:] if argv is None else argv)

    if not arguments or arguments[0] in {"-h", "--help"}:
        stdout.write(HELP)
        return 0

    command = arguments[0]
    if command not in {"start", "pause", "resume", "stop", "profile"}:
        stderr.write(
            f"Error: Unknown command: {command}\n\n"
            "Run `focus --help` for usage.\n"
        )
        return 2
    no_argument_commands = {"pause", "resume", "stop", "profile"}
    if command in no_argument_commands and len(arguments) != 1:
        usage = f"focus {command}"
        stderr.write(
            f"Error: The {command} command does not accept arguments.\n\n"
            f"Usage:\n  {usage}\n"
        )
        return 2

    # Validate before touching local storage. Argument mistakes should always
    # produce exit code 2, even when the database location is unavailable.
    start_options = None
    if command == "start":
        start_options = start_parser(stdout=stdout, stderr=stderr).parse_args(
            arguments[1:]
        )

    storage = FocusStorage(database_path)
    try:
        storage.initialize()
        # Start performs the same recovery inside its creation transaction so
        # recovery and creation remain atomic. Stop chooses completion itself at
        # the boundary. These calls still satisfy command-start recovery without
        # introducing a race between separate processes.
        if command == "start":
            return _run_start(start_options, storage, stdin=stdin, stdout=stdout)
        if command == "pause":
            return _run_pause(storage, stdout)
        if command == "resume":
            return _run_resume(storage, stdin=stdin, stdout=stdout)
        if command == "stop":
            return _run_stop(storage, stdout)
        return _run_profile(storage, stdout)
    except (OSError, sqlite3.Error):
        path = database_path or default_database_path()
        stderr.write(
            "Error: Focus could not access its local database.\n\n"
            f"Path:\n  {path}\n"
        )
        return 1
    except RuntimeError as error:
        stderr.write(f"Error: {error}\n")
        return 1
    except Exception:
        stderr.write("Error: Focus encountered an internal failure.\n")
        return 1


def entrypoint() -> None:
    raise SystemExit(main())
