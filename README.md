# Focus CLI

Focus CLI is a small, local-first focus timer. Start a session, keep a clear
countdown on screen, and earn one XP per focused minute plus a 20% bonus when
you complete the full timer.

## Demo
https://github.com/user-attachments/assets/064aa8d8-8f3b-4690-89ea-8d1bd48b73eb

## Install

Focus CLI requires Python 3.9 or newer and has no third-party runtime
dependencies.

```bash
python3 -m pip install .
```

For an isolated editable development install:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

## Use

```bash
focus start 25
focus start 60 -t "Working on Math Möbius"
focus start 90 --title "Implementing authentication"
focus pause
focus resume
focus stop
focus profile
focus delete latest
focus config name "Lemuel"
```

Only one session can be current. Use `focus pause` to freeze its countdown and
`focus resume` to continue without counting the break as focus time. Pause and
stop can be issued in the timer's input line or from another terminal. Pressing
Ctrl+C closes only the live display; the persisted session keeps running until
paused, stopped, or completed.

Set your profile name with `focus config name "Lemuel"`. `focus profile` shows
the configured name, your XP, and every recorded session, including sessions
that are active, paused, or were stopped early.

Permanently remove the newest session with `focus delete latest`. This also
removes any XP awarded by that session. Other sessions and profile settings are
left unchanged.

Run `focus --help` for the complete command summary.

## Data

Sessions are stored in SQLite at the standard per-user data location:

- macOS: `~/Library/Application Support/focus/focus.db`
- Linux: `~/.local/share/focus/focus.db` (or `$XDG_DATA_HOME/focus/focus.db`)
- Windows: `%APPDATA%\focus\focus.db`

For portable use or testing, set `FOCUS_DB_PATH` to a database filename, or
set `FOCUS_DATA_DIR` to override its containing directory.

## Development

```bash
python -m unittest discover -s tests -v
```
