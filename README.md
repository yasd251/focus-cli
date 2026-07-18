# Focus CLI

Focus CLI is a small, local-first focus timer. Start a session, keep a clear
countdown on screen, and earn one XP per focused minute plus a 20% bonus when
you complete the full timer.

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
focus stop
```

Only one session can be active. `focus stop` can be issued in the timer's
input line or from another terminal. Pressing Ctrl+C closes only the live
display; the persisted session keeps running until stopped or completed.

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
