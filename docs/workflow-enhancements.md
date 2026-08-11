# Kiro-CLI Workflow Enhancements Brainstorming & Architectural Design

This document details five developer workflow enhancements that leverage the rich session state, transcripts, and file tracking data stored in the `kiro-cli` SQLite database (`data.sqlite3`). These features transform `kiro-cli` from a simple interactive chat agent into an integrated assistant driving the developer's daily workflow.

---

## 1. Workspace Restore

### Concept
When returning to a project or continuing an older session, developers often spend several minutes reopening the specific files, finding the right line numbers, and recovering mental context. `Workspace Restore` automatically reopens the exact files the developer was working on during that specific session.

### Schema & Data Leverage
- **Source Table:** `conversations_v2`
- **JSON Field:** `file_line_tracker` (an object tracking files read or modified during the session).
- **Target Value:** Absolute file paths.

### Architectural Design
1. Retrieve the session state JSON from the database.
2. Extract the file paths from the `file_line_tracker` dictionary.
3. Filter out paths that no longer exist on the local file system.
4. Detect the developer's active editor (e.g., VS Code via `code`, Cursor via `cursor`, or console editors like `vim`/`nano` via environmental variables).
5. Execute the editor's CLI command to open all tracked files at once.
   - Example for VS Code: `code /path/to/file1.py /path/to/file2.py`

---

## 2. Conventional Commit Draft

### Concept
Writing clean, descriptive commit messages matching conventional standards (e.g., `feat(<scope>): <summary>`) is a tedious task. `Conventional Commit Draft` auto-generates a Git commit message based on the actual changes, tools run, and assistant conversations during the session.

### Schema & Data Leverage
- **Source Table:** `conversations_v2`
- **JSON Field:** `latest_summary` (summary of what was achieved), `transcript` (to parse user intents and files discussed), and `file_line_tracker` (to identify modified files and package scopes).

### Architectural Design
1. Locate the latest active session for the project directory.
2. Extract the modified files from the `file_line_tracker`. Group files by directory or file type to automatically infer the commit scope (e.g., `api` or `docs`).
3. Analyze the session's `latest_summary` or first user query to determine the commit type (`feat`, `fix`, `chore`, `docs`, etc.).
4. Format a conventional commit message:
   ```
   feat(scope): short description based on latest_summary

   Changes made:
   - Modified: path/to/file1.py
   - Modified: path/to/file2.py
   ```
5. Offer to pass the output to `git commit -e -m <drafted_message>` so the developer can review and edit.

---

## 3. Standup & Journal Generator

### Concept
Developers spend significant time compiling status reports for daily standups, weekly summaries, or personal development journals. The `Standup & Journal Generator` aggregates all developer sessions over a given timeframe or across a project to create a chronological digest of actions taken, problems solved, and files touched.

### Schema & Data Leverage
- **Source Tables:** Both `conversations_v2` and legacy `conversations` tables.
- **Fields:** `key` (project directory), `updated_at` (unix timestamp in milliseconds), and JSON fields like `latest_summary`, `transcript`, and `model_info`.

### Architectural Design
1. Query the database for all sessions matching the specified project directory (`key`), wrapping `conversations_v2` and `conversations` in a `UNION ALL` subquery to filter by directory and sort chronologically by `updated_at`.
2. Iterate through each session and parse its JSON state:
   - Extract the timestamp and format it as a human-readable date.
   - Extract the first user query to represent the session's goal.
   - Extract the `latest_summary` as the session outcome (falling back to the last assistant response if a summary is not yet generated).
3. Print a clean, formatted chronological markdown log summarizing the history, highlighting files touched and solutions provided.

---

## 4. Session Forking

### Concept
When experimenting with different solutions (e.g., trying a refactoring approach vs. a complete redesign), developers want to branch their chat conversation just like a Git branch, allowing them to pursue parallel avenues of thought without corrupting the main session history.

### Schema & Data Leverage
- **Source Table:** `conversations_v2`
- **Fields:** `conversation_id` (composite PK with directory `key`), `value` (JSON state blob).

### Architectural Design
1. Fetch the JSON state blob of the session to be forked.
2. Generate a new unique UUID for `conversation_id`.
3. In the JSON blob, update the `conversation_id` field to the new UUID, keeping the message history up to the current point.
4. Insert the cloned record into the database with the new `conversation_id` and the current timestamp for `created_at` and `updated_at`.
5. Switch active focus to the newly forked session, enabling isolated exploration.

---

## 5. Terminal Failure Auto-Healer

### Concept
When running test suites, builds, or scripts, developers often encounter terminal errors. The `Terminal Failure Auto-Healer` intercepts the exit code or command output of the last failed shell command and automatically starts a new `kiro-cli` session with the full terminal error context pre-loaded, ready to fix the bug.

### Schema & Data Leverage
- **Source Tables:** `history` (shell command history containing `command`, `cwd`, `exit_code`, and timestamps) and `conversations_v2`.

### Architectural Design
1. Query the `history` table to find the most recent shell command where `exit_code != 0`.
2. Extract the command string, working directory (`cwd`), and error output.
3. Automatically initiate a `kiro-cli` session or append a next message in `conversations_v2` containing:
   - "My command `<failed_command>` failed with exit code `<exit_code>`. Here is the error context. Please suggest and implement a fix."
4. Resume the session instantly for the user, saving copying-and-pasting effort.
