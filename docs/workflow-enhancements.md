# Kiro Developer Workflow Enhancements - Architectural Design

This document details five developer workflow features that leverage the rich session metadata and history tracked by `kiro-cli` inside its SQLite database (`data.sqlite3`). These features are designed to complement the global session resume mechanism of `kiro-sessionizer` and drive concrete developer productivity enhancements directly from past chat sessions.

---

## 1. Workspace Restore (`restore`)

### Problem Statement
When a developer resumes a chat session from days or weeks ago, they must manually remember which files they were working on, find them in their editor, and reopen them. This context-switching overhead slows down resumption.

### Core Idea
Every `kiro-cli` session's JSON state (`value`) contains a `file_line_tracker` field that tracks which files were discussed, read, or modified during that session. We can extract these paths, filter for those that still exist on disk, and open them in the developer's preferred editor (e.g., VS Code, Cursor, Vim, Nano) or present them in an interactive nested `fzf` file picker.

### DB Schema & Logic Leverage
- Query `file_line_tracker` from `conversations_v2.value`.
- Extract file paths (using absolute paths or resolving them relative to the session's workspace `key`).
- Filter out non-existent files.
- Command: `kiro-sessionizer restore <session_id>` or trigger via `ctrl-o` keybinding directly inside the main `fzf` session picker.

---

## 2. Conventional Commit Draft (`commit-draft`)

### Problem Statement
After a long work session, writing a concise, conventional, and accurate commit message that lists the affected files and encapsulates the changes is tedious.

### Core Idea
Generate a draft Git commit message by reading the files modified during the session and the session's AI-generated summary/last message.

### DB Schema & Logic Leverage
- Retrieve `latest_summary` or the last message from the session transcript.
- Retrieve the files tracked in `file_line_tracker` under the session.
- Format a Git commit message following conventional commits, e.g.:
  ```
  feat: summary of session changes

  Session summary:
  - <Session latest_summary or last message>

  Files modified:
  - <List of files from file_line_tracker>
  ```
- Command: `kiro-sessionizer commit-draft`

---

## 3. Daily Standup / Project Journal Generator (`report` & `journal`)

### Problem Statement
Writing daily standup updates or keeping a chronological journal of project development requires manual logging and remembering details from multiple sessions.

### Core Idea
Automatically aggregate and format developer activity into a beautifully structured Markdown standup report or a chronological project journal using the timestamps and transcripts in the DB.

### DB Schema & Logic Leverage
- For `report`: Query all sessions updated within the last `--days` (e.g. 1 or 7), optionally filtered by `--project`. Extract the metadata (date, model, message count, initial query, latest summary, files touched) and generate a daily/weekly standup report.
- For `journal`: Query all sessions associated with a specific project directory (`key`), sort chronologically by `updated_at`, and extract the first query and latest summary to construct a project development log.
- Commands:
  - `kiro-sessionizer report [--days N] [--project NAME]`
  - `kiro-sessionizer journal [path]`

---

## 4. Interactive Project Navigation (`jump`)

### Problem Statement
Developers frequently switch between project directories. While they can use standard shells or directories bookmarks, they lack a way to instantly jump to their most recently active development workspaces.

### Core Idea
Provide an interactive project navigation command (`jump`) that displays unique project paths ordered by their most recent activity, allowing developers to jump directly to any active workspace.

### DB Schema & Logic Leverage
- Query unique `key` paths from `conversations_v2` and legacy `conversations` tables.
- Sort them in Python by the maximum `updated_at` timestamp.
- Present them in an `fzf` interactive menu.
- Shell Integration: Evaluate the `cd <path>` output to change the parent shell's directory.
- Command: `kiro-sessionizer jump`

---

## 5. Database Maintenance & Cleanup (`prune`)

### Problem Statement
`kiro-cli` never cleans up session state. Over months of use, the SQLite database can grow extremely large and contain hundreds of stale or short 1-2 message sessions, slowing down search and loading.

### Core Idea
Provide a clean maintenance mechanism to safely prune old sessions according to specific criteria, with dry-run support to prevent accidental data loss.

### DB Schema & Logic Leverage
- Filter sessions older than `--days` (e.g., 30 days) and/or with fewer than `--min-messages` (e.g., 3 messages).
- Delete matching rows from `conversations_v2` and `conversations`.
- Delete corresponding session files (`.json`, `.lock`) from `~/.kiro/sessions/cli/`.
- Prompt for interactive confirmation unless `--force` or `--apply` (dry-run mode is default).
- Command: `kiro-sessionizer prune [--days N] [--min-messages M] [--apply] [--force]`
