"""Human-facing formatting and the live countdown display."""

from __future__ import annotations

import math
import os
import queue
import shutil
import sys
import threading
import time
from datetime import datetime
from typing import Callable, Optional, TextIO

from .model import FinalizedSession, Session
from .storage import FocusStorage


def display_title(title: Optional[str]) -> str:
    return title if title else "No description"


def format_clock(seconds: int, show_hours: bool = False) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if show_hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours * 60 + minutes:02d}:{secs:02d}"


def format_elapsed(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    if minutes and secs:
        return f"{minutes}m {secs}s"
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"


def format_time(timestamp: float) -> str:
    value = datetime.fromtimestamp(timestamp).strftime("%I:%M %p")
    return value.lstrip("0")


def format_remaining_words(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def final_summary(finalized: FinalizedSession, recovered: bool = False) -> str:
    session = finalized.session
    lines: list[str]
    if recovered:
        lines = ["Recovered completed session.", ""]
    elif session.status == "completed":
        lines = ["✓ Focus session complete", ""]
    else:
        lines = ["Session stopped.", ""]

    lines.append(f"Focused for: {format_elapsed(session.actual_seconds or 0)}")
    if session.status == "stopped":
        lines.append(f"Planned:     {session.planned_minutes}m")
    lines.append(f"XP earned:   +{session.xp_awarded} XP")
    if not recovered:
        lines.append(f"Total XP:    {finalized.total_xp} XP")
    lines.extend(["", display_title(session.title)])
    return "\n".join(lines)


class TimerDisplay:
    """Render an accurate timer while treating the database as authoritative."""

    def __init__(
        self,
        storage: FocusStorage,
        session: Session,
        *,
        stdin: TextIO = sys.stdin,
        stdout: TextIO = sys.stdout,
        now: Callable[[], float] = time.time,
        tick_seconds: float = 1.0,
    ) -> None:
        self.storage = storage
        self.session = session
        self.stdin = stdin
        self.stdout = stdout
        self.now = now
        self.tick_seconds = tick_seconds
        self.interactive = bool(
            getattr(stdin, "isatty", lambda: False)()
            and getattr(stdout, "isatty", lambda: False)()
        )
        self._commands: queue.Queue[str] = queue.Queue()
        self._input_thread: Optional[threading.Thread] = None

    def _start_input_reader(self) -> None:
        if not self.interactive:
            return

        def read_commands() -> None:
            while True:
                try:
                    line = self.stdin.readline()
                except (OSError, ValueError):
                    return
                if line == "":
                    return
                self._commands.put(line.strip())

        self._input_thread = threading.Thread(target=read_commands, daemon=True)
        self._input_thread.start()

    def _render(self, now: float) -> None:
        remaining = max(0, math.ceil(self.session.planned_end_at - now))
        elapsed = max(0, self.session.planned_seconds - remaining)
        progress = min(1.0, elapsed / self.session.planned_seconds)
        percent = min(100, int(round(progress * 100)))

        terminal_width = shutil.get_terminal_size(fallback=(80, 24)).columns
        box_width = max(34, min(50, terminal_width - 4))
        inner_width = box_width - 2
        heading = "FOCUS SESSION".center(inner_width)
        timer = format_clock(remaining, self.session.planned_minutes > 99)

        bar_width = max(10, min(32, terminal_width - 14))
        filled = min(bar_width, int(progress * bar_width))
        bar = "█" * filled + "░" * (bar_width - filled)

        lines = [
            "╭" + "─" * inner_width + "╮",
            "│" + heading + "│",
            "╰" + "─" * inner_width + "╯",
            "",
            timer.center(min(terminal_width, box_width)),
            "",
            f"  {bar}  {percent}%",
            "",
            f"  {display_title(self.session.title)}",
            "",
            f"  Started: {format_time(self.session.started_at)}",
            f"  Ends:    {format_time(self.session.planned_end_at)}",
            "",
            '  Type "focus stop" and press Enter to stop.',
            "",
            "> ",
        ]
        self.stdout.write("\x1b[H" + "\n".join(lines) + "\x1b[J")
        self.stdout.flush()

    def _clear_live_display(self) -> None:
        if self.interactive:
            self.stdout.write("\x1b[?25h\x1b[2J\x1b[H")
            self.stdout.flush()

    def _result_for_existing(self, session: Session) -> FinalizedSession:
        return FinalizedSession(session=session, total_xp=self.storage.total_xp())

    def run(self) -> Optional[FinalizedSession]:
        """Run until finalized; return ``None`` only when the display is closed."""

        self._start_input_reader()
        if self.interactive:
            self.stdout.write("\x1b[2J\x1b[H\x1b[?25l")
            self.stdout.flush()
        else:
            self.stdout.write(
                f"Focus session started for {self.session.planned_minutes}m.\n"
                f"{display_title(self.session.title)}\n"
            )
            self.stdout.flush()

        try:
            while True:
                current_time = self.now()
                if current_time >= self.session.planned_end_at:
                    finalized = self.storage.complete_session(
                        self.session.id, current_time
                    )
                    if finalized is None:
                        current = self.storage.get_session(self.session.id)
                        if current is not None and current.status != "active":
                            finalized = self._result_for_existing(current)
                    if finalized is not None:
                        self._clear_live_display()
                        return finalized

                current = self.storage.get_session(self.session.id)
                if current is None:
                    raise RuntimeError("The active session record disappeared.")
                if current.status != "active":
                    self._clear_live_display()
                    return self._result_for_existing(current)

                if self.interactive:
                    self._render(current_time)

                try:
                    command = self._commands.get_nowait()
                except queue.Empty:
                    command = ""
                if command == "focus stop":
                    finalized = self.storage.stop_active(self.now())
                    if finalized is not None:
                        self._clear_live_display()
                        return finalized

                # Anchor each refresh to wall-clock boundaries where practical.
                delay = min(
                    self.tick_seconds,
                    max(0.01, self.session.planned_end_at - self.now()),
                )
                time.sleep(delay)
        except KeyboardInterrupt:
            self._clear_live_display()
            return None
        finally:
            if self.interactive:
                self.stdout.write("\x1b[?25h")
                self.stdout.flush()

