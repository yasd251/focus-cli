# Focus CLI — MVP Product Specification

## 1. Product Overview

**Focus CLI** is a minimal command-line focus timer with lightweight progression.

Users start a timed focus session, optionally describe what they are working on, and earn XP based on how long they focus. The tool should make completing a session feel satisfying without becoming a full task manager, habit tracker, or productivity suite.

### Core loop

1. Start a focus session.
2. Watch a clear countdown.
3. Stop early or complete the timer.
4. Record the session.
5. Earn XP.
6. Return later and repeat.

---

## 2. Product Principles

### Focus on one thing

The tool should do focus sessions extremely well. It should not include projects, task lists, calendars, reminders, or complex productivity systems in the MVP.

### Fast to start

Starting a session should require only one command:

```bash
focus start 60
```

### Reward real focus

XP should be based primarily on the amount of time actually spent focusing. Completing the full planned session should provide a small bonus.

### Local-first

All session data should be stored locally. No account, internet connection, or cloud service should be required.

### Reliable timing

The countdown must remain accurate even when the computer sleeps, the terminal lags, or the timer process temporarily stops rendering.

---

## 3. MVP Commands

The first version has two primary commands:

```bash
focus start <minutes>
focus stop
```

Optional metadata can be added using:

```bash
focus start <minutes> -t "<description>"
```

The long-form version should also be supported:

```bash
focus start <minutes> --title "<description>"
```

Examples:

```bash
focus start 25
focus start 60 -t "Working on Math Möbius"
focus start 90 --title "Implementing authentication"
focus stop
```

---

# 4. Starting a Focus Session

## Command

```bash
focus start <minutes> [options]
```

## Arguments

### `<minutes>`

The planned duration of the session in whole minutes.

Examples:

```bash
focus start 25
focus start 60
focus start 120
```

### Validation

The duration must:

* Be a whole number.
* Be greater than zero.
* Be no greater than 1,440 minutes.
* Not contain units such as `60m`.

Valid:

```bash
focus start 60
```

Invalid:

```bash
focus start
focus start zero
focus start -20
focus start 1.5
focus start 60m
focus start 2000
```

Error example:

```text
Error: Duration must be between 1 and 1440 minutes.

Usage:
  focus start <minutes> [-t "description"]
```

---

## Title option

```bash
-t, --title <text>
```

The title describes what the user intends to work on.

Example:

```bash
focus start 60 -t "Working on Math Möbius"
```

The title should:

* Be optional.
* Be displayed underneath the timer.
* Be saved with the completed session.
* Preserve spaces and punctuation.
* Be limited to 200 characters.
* Be trimmed of leading and trailing whitespace.

If no title is provided, display:

```text
No description
```

The stored title may remain `null` rather than storing the text `"No description"`.

---

# 5. Active Timer Interface

After starting a session, the terminal should switch into a clean live countdown view.

Example:

```text
╭──────────────────────────────────────────╮
│               FOCUS SESSION              │
╰──────────────────────────────────────────╯

                      59:42

  ████████████████████░░░░░░░░░░░░  1%

  Working on Math Möbius

  Started: 10:32 AM
  Ends:    11:32 AM

  Type "focus stop" and press Enter to stop.

> 
```

## Timer requirements

The timer should:

* Update once per second.
* Render in place rather than printing a new line every second.
* Show time in `MM:SS`.
* Use `HH:MM:SS` for sessions longer than 99 minutes.
* Show a visual progress bar.
* Display the session title.
* Display the start time.
* Display the expected finish time.
* Avoid excessive animations or terminal flickering.

## Timer accuracy

The timer must calculate remaining time using timestamps:

```text
remaining = planned_end_time - current_time
```

It must not rely only on decrementing a number once per second.

This prevents timer drift when:

* The terminal freezes.
* The process is temporarily paused.
* The computer sleeps.
* Rendering takes longer than expected.

---

# 6. Stopping a Session

## Command

```bash
focus stop
```

A session may be stopped in either of two ways.

### From the active timer

The timer interface should provide an input line. The user can type:

```text
focus stop
```

and press Enter.

The timer should stop immediately.

### From another terminal

While a session is running, the user can open another terminal and run:

```bash
focus stop
```

The original timer display should detect the change within one second and exit cleanly.

---

## Stop behavior

When a session is stopped early:

1. Calculate the actual elapsed focus time.
2. Mark the session as `stopped`.
3. Save it to the session history.
4. Calculate XP based on the actual duration.
5. Show a session summary.
6. Clear the active-session state.

Example:

```text
Session stopped.

Focused for: 37m 24s
Planned:     60m
XP earned:   +37 XP
Total XP:    284 XP

Working on Math Möbius
```

---

## No active session

Running `focus stop` without an active session should return:

```text
No focus session is currently active.
```

This should not be treated as a fatal error.

---

# 7. Completing a Session

When the countdown reaches zero:

1. Mark the session as `completed`.
2. Save the session.
3. Calculate the session XP.
4. Add the completion bonus.
5. Clear the active-session state.
6. Show a completion summary.
7. Optionally play a terminal bell.

Example:

```text
✓ Focus session complete

Focused for: 60m
XP earned:   +72 XP
Total XP:    319 XP

Working on Math Möbius
```

The terminal bell should be subtle and may be disabled automatically when output is not connected to an interactive terminal.

---

# 8. XP System

The XP system should be understandable without needing documentation.

## Base XP

Award:

```text
1 XP for each completed minute of actual focus time
```

Formula:

```text
base_xp = floor(actual_focus_seconds / 60)
```

Examples:

| Actual focus time | Base XP |
| ----------------: | ------: |
|            4m 59s |    4 XP |
|               25m |   25 XP |
|           37m 24s |   37 XP |
|               60m |   60 XP |

Sessions shorter than one minute earn zero XP.

---

## Completion bonus

A session completed without being stopped early receives a 20% bonus.

Formula:

```text
completion_bonus = ceil(base_xp × 0.20)
```

Total:

```text
session_xp = base_xp + completion_bonus
```

Examples:

| Planned and completed | Base XP | Bonus |  Total |
| --------------------: | ------: | ----: | -----: |
|                   10m |      10 |     2 |  12 XP |
|                   25m |      25 |     5 |  30 XP |
|                   45m |      45 |     9 |  54 XP |
|                   60m |      60 |    12 |  72 XP |
|                   90m |      90 |    18 | 108 XP |

Stopped sessions receive base XP but no completion bonus.

This rewards both:

* Spending genuine time focusing.
* Finishing the duration the user committed to.

---

## XP integrity

XP should only be awarded when a session is finalized.

The same session must never award XP more than once, even if:

* The terminal crashes.
* The user runs `focus stop` repeatedly.
* The application is restarted.
* Session recovery runs more than once.

Each session should have a unique identifier and a stored `xp_awarded` value.

---

# 9. Preventing Concurrent Sessions

Only one focus session may be active at a time.

If the user runs:

```bash
focus start 25
```

while another session is already active, return:

```text
A focus session is already running.

Remaining: 42m 18s
Title: Working on Math Möbius

Use `focus stop` to end the current session.
```

The new session must not be created.

---

# 10. Session Persistence

The active session must not exist only in process memory.

When a session starts, immediately write its state to local storage.

This allows:

* `focus stop` to work from another terminal.
* The timer to recover after a crash.
* Sessions to survive terminal closure.
* Duplicate sessions to be prevented.

## Suggested storage location

Linux:

```text
~/.local/share/focus/focus.db
```

macOS:

```text
~/Library/Application Support/focus/focus.db
```

Windows:

```text
%APPDATA%\focus\focus.db
```

SQLite is recommended because it provides:

* Atomic writes.
* Reliable locking.
* Easy session history queries.
* Protection against partially written JSON.
* Room for future statistics without changing storage formats.

A JSON file may be used for an early prototype, but SQLite is preferred for the proper MVP.

---

# 11. Data Model

## Sessions table

```text
sessions
```

| Field             | Type                | Description                         |
| ----------------- | ------------------- | ----------------------------------- |
| `id`              | UUID or text        | Unique session identifier           |
| `title`           | text, nullable      | Optional session description        |
| `planned_minutes` | integer             | Requested session length            |
| `started_at`      | timestamp           | Time the session began              |
| `planned_end_at`  | timestamp           | Expected completion time            |
| `ended_at`        | timestamp, nullable | Actual finish time                  |
| `actual_seconds`  | integer, nullable   | Actual elapsed duration             |
| `status`          | text                | `active`, `completed`, or `stopped` |
| `base_xp`         | integer             | XP earned from elapsed time         |
| `bonus_xp`        | integer             | Completion bonus                    |
| `xp_awarded`      | integer             | Total XP awarded                    |
| `created_at`      | timestamp           | Record creation time                |

## Application state

Only one session should have:

```text
status = active
```

The database should enforce or validate this invariant.

---

# 12. Session Recovery

Every command should begin by checking whether an active session exists.

## Active session has passed its end time

When the current time is later than `planned_end_at`, the application should automatically finalize the session as completed.

Example:

1. User starts a 60-minute session.
2. User closes the terminal.
3. Sixty minutes pass.
4. User later runs another Focus CLI command.
5. The previous session is finalized as completed.
6. XP is awarded once.

The application should show:

```text
Recovered completed session.

Focused for: 60m
XP earned:   +72 XP
```

## Active session has not reached its end time

The session remains active.

Running the original start command again should show the existing session rather than create a new one.

## Computer sleep

Elapsed time should continue to count while the computer is asleep.

For the MVP, Focus CLI measures wall-clock time, not whether the user was actively using the computer.

---

# 13. Process and Communication Model

The tool should not require a permanently running daemon.

## Recommended approach

1. `focus start` creates an active session record.
2. The command displays the countdown.
3. The countdown checks the database every second.
4. `focus stop` updates the active session record.
5. The countdown notices that the session is no longer active and exits.
6. If the countdown process closes, the stored timestamps remain authoritative.

This approach keeps the application simple while allowing control from multiple terminals.

## Database locking

Session creation and session stopping should use transactions to prevent race conditions.

For example, two simultaneous `focus start` commands must not create two active sessions.

---

# 14. Interrupt Handling

## Ctrl+C

Pressing `Ctrl+C` should not silently discard or automatically stop the session.

Instead, display:

```text
Timer display closed. Your focus session is still running.

Run `focus stop` to stop it.
```

The session remains active in storage.

This distinguishes:

* Closing the timer display.
* Stopping the actual focus session.

## Unexpected crash

If the display crashes, the session remains active and can be recovered using timestamps.

## Terminal closure

Closing the terminal should behave the same as closing the timer display. It should not stop the session.

---

# 15. Output and Exit Codes

## Successful start

```text
Exit code: 0
```

The command remains attached while displaying the timer.

## Successful stop

```text
Exit code: 0
```

## No active session when stopping

```text
Exit code: 0
```

This is an informational state.

## Invalid arguments

```text
Exit code: 2
```

## Storage or internal failure

```text
Exit code: 1
```

Errors should be concise and actionable.

Bad:

```text
An unexpected exception occurred in database adapter line 271.
```

Better:

```text
Error: Focus could not access its local database.

Path:
  ~/.local/share/focus/focus.db
```

---

# 16. Help Output

```text
Focus CLI

A minimal focus timer that rewards completed sessions with XP.

Usage:
  focus start <minutes> [options]
  focus stop

Commands:
  start    Start a focus session
  stop     Stop the active focus session

Start options:
  -t, --title <text>    Describe what you are focusing on
  -h, --help            Show command help

Examples:
  focus start 25
  focus start 60 -t "Working on Math Möbius"
  focus stop
```

---

# 17. MVP User Flows

## Flow A: Complete an untitled session

```bash
focus start 25
```

Expected result:

* A 25-minute countdown appears.
* The title area displays `No description`.
* The timer reaches zero.
* The session is recorded as completed.
* The user earns 25 base XP and 5 bonus XP.
* The final summary displays `+30 XP`.

---

## Flow B: Complete a titled session

```bash
focus start 60 -t "Working on Math Möbius"
```

Expected result:

* A 60-minute countdown appears.
* `Working on Math Möbius` is displayed underneath it.
* The session is saved with that title.
* The user earns 72 XP after completing the session.

---

## Flow C: Stop a session early

```bash
focus start 60 -t "Working on Math Möbius"
```

After approximately 37 minutes:

```bash
focus stop
```

Expected result:

* The timer ends.
* The session is recorded as stopped.
* Actual focus time is approximately 37 minutes.
* The user earns approximately 37 XP.
* No completion bonus is awarded.

---

## Flow D: Stop from another terminal

Terminal one:

```bash
focus start 60
```

Terminal two:

```bash
focus stop
```

Expected result:

* Terminal two finalizes the session.
* Terminal one detects the stopped session within one second.
* Both commands exit cleanly.
* XP is awarded exactly once.

---

## Flow E: Attempt to start a second session

```bash
focus start 60
focus start 25
```

Expected result:

* The first session remains active.
* The second command explains that a session is already running.
* No second session is created.

---

# 18. MVP Acceptance Criteria

The MVP is complete when all of the following are true:

* `focus start 60` starts an accurate 60-minute countdown.
* `focus start 60 -t "Working on Math Möbius"` displays and stores the title.
* The timer updates in place once per second.
* A session can be stopped using `focus stop`.
* A session can be stopped from another terminal.
* Closing the timer display does not stop the session.
* Only one session can be active.
* Completed sessions receive base XP and a completion bonus.
* Stopped sessions receive XP based on actual elapsed minutes.
* Session XP cannot be awarded twice.
* Sessions are logged locally.
* Active sessions can be recovered after a crash or terminal closure.
* Invalid durations produce useful errors.
* The tool works without an internet connection.

---

# 19. Out of Scope for the MVP

The first version should not include:

* Task management.
* Projects or categories.
* To-do lists.
* Calendar integration.
* Accounts or authentication.
* Cloud synchronization.
* Teams or social features.
* Leaderboards.
* Achievements.
* Streaks.
* Shops or unlockable rewards.
* Pomodoro break automation.
* Website blocking.
* Application blocking.
* AI-generated productivity advice.
* Configurable XP formulas.
* Mobile or graphical interfaces.

These features may be considered later, but they should not delay the core timer experience.

---

# 20. Possible Post-MVP Commands

These are natural additions once starting and stopping sessions are reliable.

```bash
focus status
focus history
focus stats
```

Potential behavior:

```bash
focus status
```

```text
Current session

Remaining: 42m 18s
Title: Working on Math Möbius
Started: 10:32 AM
Ends: 11:32 AM
```

```bash
focus history
```

```text
Recent sessions

Today
✓ 60m  Working on Math Möbius       +72 XP
■ 37m  Implementing authentication  +37 XP
✓ 25m  No description               +30 XP
```

```bash
focus stats
```

```text
Total XP:       1,284
Total focus:    18h 42m
Sessions:       27
Completed:      22
Stopped early:  5
```

These commands should remain outside the initial implementation unless visibility into stored history becomes necessary during development.

---

# 21. Recommended MVP Build Order

## Phase 1: Core timer

* Parse `focus start <minutes>`.
* Render an accurate countdown.
* Handle reaching zero.
* Handle invalid input.

## Phase 2: Persistence

* Create the SQLite database.
* Store active sessions.
* Prevent concurrent sessions.
* Finalize completed sessions.

## Phase 3: Stop command

* Implement `focus stop`.
* Allow stopping from another terminal.
* Poll session state from the timer.
* Handle repeated stop commands safely.

## Phase 4: Titles and summaries

* Add `-t` and `--title`.
* Display the title beneath the timer.
* Save the title.
* Show completion and stop summaries.

## Phase 5: XP

* Calculate base XP.
* Calculate completion bonuses.
* Store total XP per session.
* Prevent duplicate XP awards.

## Phase 6: Recovery and polish

* Recover sessions after crashes.
* Handle Ctrl+C correctly.
* Improve terminal rendering.
* Add automated tests for timing and concurrency.

---

# 22. One-Sentence Product Definition

> Focus CLI is a local-first command-line timer that makes starting, completing, and earning XP from focused work sessions fast and satisfying.
