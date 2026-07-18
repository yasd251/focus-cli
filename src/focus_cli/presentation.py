"""Human-facing formatting and the live countdown display."""

from __future__ import annotations

import math
import os
import queue
import shutil
import sys
import threading
import time
import textwrap
from datetime import datetime
from typing import Callable, Optional, Sequence, TextIO

from .model import FinalizedSession, Session
from .storage import FocusStorage


ACCENT_RED = "\x1b[38;2;239;68;68m"
TITLE_GOLD = "\x1b[38;2;251;191;36m"
DATE_BLUE = "\x1b[38;2;148;163;184m"
MUTED = "\x1b[38;2;115;115;115m"
BOLD = "\x1b[1m"
RESET = "\x1b[0m"

PROFILE_AVATAR = (
    "╭─────────╮",
    "│  ╭───╮  │",
    "│  │ F │  │",
    "│  ╰───╯  │",
    "╰─────────╯",
)

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


def format_date(timestamp: float) -> str:
    value = datetime.fromtimestamp(timestamp)
    return f"{value.strftime('%A, %B')} {value.day}, {value.year}"


def format_session_datetime(timestamp: float) -> str:
    value = datetime.fromtimestamp(timestamp)
    time_text = value.strftime("%I:%M %p").lstrip("0").lower()
    return (
        f"{value.strftime('%A')}, {value.day} {value.strftime('%B')} "
        f"{value.year}, {time_text}"
    )


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
        lines = ["Focus session complete", ""]
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


def profile_view(
    sessions: Sequence[Session],
    total_xp: int,
    now: float,
    *,
    interactive: bool = False,
    width: Optional[int] = None,
) -> str:
    """Render the complete focus profile without aggregate productivity stats."""

    terminal_width = width or shutil.get_terminal_size(fallback=(80, 24)).columns
    terminal_width = max(36, terminal_width)
    lines: list[str] = [""]
    for avatar_line in PROFILE_AVATAR:
        centered = avatar_line.center(terminal_width)
        lines.append(ACCENT_RED + centered + RESET if interactive else centered)

    xp_line = f"{total_xp} XP".center(terminal_width)
    lines.extend(
        [
            "",
            BOLD + TITLE_GOLD + xp_line + RESET if interactive else xp_line,
            "",
            "Sessions",
            "─" * min(terminal_width, 80),
        ]
    )

    if not sessions:
        lines.append("No focus sessions yet.")
        return "\n".join(lines) + "\n"

    rows: list[tuple[str, str, str, str]] = []
    for session in sessions:
        if session.status == "active":
            elapsed = int(
                max(0.0, min(now, session.planned_end_at) - session.started_at)
            )
        else:
            elapsed = session.actual_seconds or 0
        duration = f"{format_elapsed(elapsed)} / {session.planned_minutes}m"
        rows.append(
            (
                session.status.upper(),
                duration,
                display_title(session.title),
                format_session_datetime(session.started_at),
            )
        )

    if terminal_width < 64:
        for status, duration, session_title, date in rows:
            status_text = f"{status:<9}"
            if interactive:
                status_color = TITLE_GOLD if status == "ACTIVE" else MUTED
                status_text = status_color + status_text + RESET
            timestamp_line = f"  Started: {date}"
            if interactive:
                timestamp_line = DATE_BLUE + timestamp_line + RESET
            lines.extend(
                [
                    f"{status_text}  {duration}",
                    "  " + session_title,
                    timestamp_line,
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"

    status_width = 9
    duration_width = max(12, min(18, max(len(row[1]) for row in rows)))
    title_width = max(
        12,
        terminal_width - status_width - duration_width - 4,
    )
    for status, duration, session_title, date in rows:
        visible_title = textwrap.shorten(
            session_title,
            width=title_width,
            placeholder="...",
        )
        status_text = f"{status:<{status_width}}"
        if interactive:
            status_color = TITLE_GOLD if status == "ACTIVE" else MUTED
            status_text = status_color + status_text + RESET
        lines.append(
            f"{status_text}  {duration:<{duration_width}}  "
            f"{visible_title:<{title_width}}"
        )
        timestamp_line = " " * (status_width + 2) + f"Started: {date}"
        if interactive:
            timestamp_line = DATE_BLUE + timestamp_line + RESET
        lines.append(timestamp_line)
    return "\n".join(lines) + "\n"


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
        self.current_xp = storage.total_xp()
        self.interactive = bool(
            getattr(stdin, "isatty", lambda: False)()
            and getattr(stdout, "isatty", lambda: False)()
        )
        self._commands: queue.Queue[str] = queue.Queue()
        self._input_thread: Optional[threading.Thread] = None
        self._input_event = threading.Event()
        self._input_buffer = ""
        self._character_input = False
        self._terminal_state = None

    def _enable_character_input(self) -> None:
        """Let Focus own echoing so timer redraws cannot erase typed text."""

        if not self.interactive:
            return
        if os.name == "nt":
            self._character_input = True
            return
        try:
            import termios
            import tty

            descriptor = self.stdin.fileno()
            self._terminal_state = (descriptor, termios.tcgetattr(descriptor))
            tty.setcbreak(descriptor)
            self._character_input = True
        except (AttributeError, OSError, ValueError):
            # Unusual TTY-like streams can still use line-based input.
            self._terminal_state = None
            self._character_input = False

    def _restore_character_input(self) -> None:
        if self._terminal_state is None:
            return
        descriptor, attributes = self._terminal_state
        try:
            import termios

            termios.tcsetattr(descriptor, termios.TCSADRAIN, attributes)
        except (OSError, ValueError):
            pass
        finally:
            self._terminal_state = None

    def _start_input_reader(self) -> None:
        if not self.interactive:
            return

        def read_commands() -> None:
            if self._character_input and os.name == "nt":
                import msvcrt

                while True:
                    character = msvcrt.getwch()
                    self._commands.put(character)
                    self._input_event.set()
            if self._character_input:
                while True:
                    try:
                        character = self.stdin.read(1)
                    except (OSError, ValueError):
                        return
                    if character == "":
                        return
                    self._commands.put(character)
                    self._input_event.set()
            while True:
                try:
                    line = self.stdin.readline()
                except (OSError, ValueError):
                    return
                if line == "":
                    return
                self._commands.put(line)
                self._input_event.set()

        self._input_thread = threading.Thread(target=read_commands, daemon=True)
        self._input_thread.start()

    def _read_command(self) -> Optional[str]:
        """Apply pending keystrokes and return a submitted command, if any."""

        submitted: Optional[str] = None
        # Clear first so a keystroke arriving during the drain leaves the event
        # set and wakes the next pass instead of being delayed until the tick.
        self._input_event.clear()
        while True:
            try:
                text = self._commands.get_nowait()
            except queue.Empty:
                break
            for character in text:
                if character == "\x03":
                    raise KeyboardInterrupt
                if character in {"\r", "\n"}:
                    candidate = self._input_buffer.strip()
                    self._input_buffer = ""
                    if candidate:
                        submitted = candidate
                elif character in {"\x08", "\x7f"}:
                    self._input_buffer = self._input_buffer[:-1]
                elif character == "\x15":  # Ctrl+U
                    self._input_buffer = ""
                elif character.isprintable():
                    self._input_buffer += character
        return submitted

    def _render(self, now: float) -> None:
        remaining = max(0, math.ceil(self.session.planned_end_at - now))
        elapsed = max(0, self.session.planned_seconds - remaining)
        progress = min(1.0, elapsed / self.session.planned_seconds)
        percent = min(100, int(round(progress * 100)))

        terminal_size = shutil.get_terminal_size(fallback=(80, 24))
        terminal_width = max(20, terminal_size.columns)
        terminal_height = max(12, terminal_size.lines)
        content_width = max(16, min(64, terminal_width - 4))
        timer = format_clock(remaining, self.session.planned_minutes > 99)

        bar_width = max(8, min(38, content_width - 8))
        filled = min(bar_width, int(progress * bar_width))
        if progress > 0 and filled == 0:
            filled = 1
        track = "━" * (bar_width - filled)
        complete = "━" * filled
        percent_text = f"{percent}%"
        progress_length = bar_width + 2 + len(percent_text)
        progress_indent = max(0, (terminal_width - progress_length) // 2)
        if self.interactive:
            progress_line = (
                " " * progress_indent
                + ACCENT_RED
                + complete
                + RESET
                + MUTED
                + track
                + RESET
                + "  "
                + ACCENT_RED
                + percent_text
                + RESET
            )
        else:
            progress_line = " " * progress_indent + complete + track + "  " + percent_text

        timer_indent = " " * max(0, (terminal_width - len(timer)) // 2)
        if self.interactive:
            timer_line = timer_indent + BOLD + timer + RESET
        else:
            timer_line = timer_indent + timer

        title_width = max(12, min(content_width, 58))
        title_lines = textwrap.wrap(
            display_title(self.session.title),
            width=title_width,
            break_long_words=True,
            break_on_hyphens=False,
        ) or ["No description"]
        if len(title_lines) > 2:
            remainder = " ".join(title_lines[1:])
            title_lines = [
                title_lines[0],
                textwrap.shorten(remainder, width=title_width, placeholder="..."),
            ]

        centered_title = [line.center(terminal_width) for line in title_lines]
        date_line = format_date(self.session.started_at).center(terminal_width)
        times = (
            f"Started {format_time(self.session.started_at)}"
            f"   Ends {format_time(self.session.planned_end_at)}"
        )
        times_line = times.center(terminal_width)
        if self.interactive:
            centered_title = [TITLE_GOLD + line + RESET for line in centered_title]
            date_line = DATE_BLUE + date_line + RESET
            times_line = MUTED + times_line + RESET

        box_width = content_width
        box_indent = max(0, (terminal_width - box_width) // 2)
        box_prefix = " " * box_indent
        input_capacity = max(1, box_width - 6)
        visible_input = self._input_buffer[-input_capacity:]
        prompt_content = f"> {visible_input}"
        top_border = box_prefix + "╭" + "─" * (box_width - 2) + "╮"
        input_line = (
            box_prefix
            + "│ "
            + prompt_content.ljust(box_width - 4)
            + " │"
        )
        bottom_border = box_prefix + "╰" + "─" * (box_width - 2) + "╯"
        hint = "Type focus stop and press Enter"
        hint_line = hint.center(terminal_width)
        if self.interactive:
            input_line = (
                box_prefix
                + "│ > "
                + visible_input.ljust(box_width - 6)
                + " │"
            )
            hint_line = MUTED + hint_line + RESET

        xp_line = f"{self.current_xp} XP".center(terminal_width)
        if self.interactive:
            xp_line = BOLD + TITLE_GOLD + xp_line + RESET

        content = [
            xp_line,
            "",
            timer_line,
            "",
            progress_line,
            "",
            *centered_title,
            date_line,
            times_line,
            "",
            top_border,
            input_line,
            bottom_border,
            hint_line,
        ]
        top_padding = max(0, (terminal_height - len(content)) // 2)
        lines = [""] * top_padding + content
        input_row = top_padding + len(content) - 3

        if self.interactive:
            rows_below_input = len(lines) - input_row - 1
            cursor_column = box_indent + 4 + len(visible_input)
            output = "\x1b[?25l\x1b[H" + "\n".join(lines) + "\x1b[J"
            if rows_below_input:
                output += f"\x1b[{rows_below_input}A"
            output += "\r"
            if cursor_column:
                output += f"\x1b[{cursor_column}C"
            output += "\x1b[?25h"
        else:
            output = "\n".join(lines)
        self.stdout.write(output)
        self.stdout.flush()

    def _clear_live_display(self) -> None:
        if self.interactive:
            self.stdout.write("\x1b[?25h\x1b[2J\x1b[H")
            self.stdout.flush()

    def _result_for_existing(self, session: Session) -> FinalizedSession:
        return FinalizedSession(session=session, total_xp=self.storage.total_xp())

    def run(self) -> Optional[FinalizedSession]:
        """Run until finalized; return ``None`` only when the display is closed."""

        self._enable_character_input()
        self._start_input_reader()
        if self.interactive:
            self.stdout.write("\x1b[2J\x1b[H\x1b[?25l")
            self.stdout.flush()
        else:
            self.stdout.write(
                f"Focus session started for {self.session.planned_minutes}m.\n"
                f"Current XP: {self.current_xp}\n"
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

                command = self._read_command()
                if command == "focus stop":
                    finalized = self.storage.stop_active(self.now())
                    if finalized is not None:
                        self._clear_live_display()
                        return finalized

                if self.interactive:
                    self._render(current_time)

                # Anchor each refresh to wall-clock boundaries where practical.
                delay = min(
                    self.tick_seconds,
                    max(0.01, self.session.planned_end_at - self.now()),
                )
                self._input_event.wait(delay)
        except KeyboardInterrupt:
            self._clear_live_display()
            return None
        finally:
            self._restore_character_input()
            if self.interactive:
                self.stdout.write("\x1b[?25h")
                self.stdout.flush()
