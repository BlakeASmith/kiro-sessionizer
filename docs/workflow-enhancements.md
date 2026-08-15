# Developer Workflow Enhancements for `kiro-sessionizer`

## Executive Summary

`kiro-sessionizer` currently provides global session search, interactive resuming (with active process detection via `.lock` files), session deletion, session dumping to Markdown (`backup`), transcript search (`search`), and basic usage statistics (`stats`).

However, `kiro-cli`'s SQLite database (`data.sqlite3`) and session JSON state blobs store rich metadata—including modified/read files (`file_line_tracker`), summarized conversation highlights (`latest_summary`), timestamped interaction logs (`history`), token/model statistics (`model_info`), and request telemetry (`user_turn_metadata`).

This document proposes 5 new workflow features designed to leverage this data to automate common developer tasks, bridge the gap between AI chat sessions and developer tools (Git, editors, standup reports), and improve long-term project maintenance.

---

## 1. Standup & Work Session Report Generator (`kiro-sessionizer report`)

### Motivation
Developers often need to summarize their work for daily standups, status updates, or client billing. Manually reviewing terminal histories or chat transcripts to recall what was done across multiple projects is tedious.

### Solution
A `report` subcommand that scans all active sessions within a given timeframe (e.g., `--today`, `--days 3`, or `--since 2026-04-01`) and aggregates key information into a clean Markdown or terminal report.

### Data Sources & DB Queries
- **`conversations_v2.updated_at` / `created_at`**: Used for timeframe filtering.
- **`key`**: Groups work by project working directory.
- **`value -> latest_summary`**: Provides concise, LLM-generated summaries of what was accomplished in each session.
- **`value -> file_line_tracker`**: Extracts a list of files modified or examined during the work sessions.
- **`value -> transcript`**: Extracts primary user intents (first query and final resolution).

### CLI Design
```bash
# Generate a standup report for today across all projects
kiro-sessionizer report --today

# Generate a report for the past 3 days for the current project
kiro-sessionizer report --days 3 --current-project

# Output as Markdown file
kiro-sessionizer report --days 7 --output standup.md
```

### Output Example
```markdown
# Work Report (2026-04-01 to 2026-04-04)

## Project: /Users/dev/projects/api-service
- **Sessions**: 3 | **Messages**: 24
- **Key Summary**: Added JWT authentication middleware and configured rate limiting.
- **Files Touched**:
  - `src/auth/jwt.ts`
  - `src/middleware/rate_limiter.ts`
  - `tests/auth.test.ts`

## Project: /Users/dev/projects/frontend-app
- **Sessions**: 1 | **Messages**: 8
- **Key Summary**: Fixed navbar responsive layout bug on mobile screens.
- **Files Touched**:
  - `src/components/Navbar.tsx`
```

---

## 2. Conventional Commit Message Drafter (`kiro-sessionizer commit-draft`)

### Motivation
After completing a session with `kiro-cli`, developers switch back to Git to commit their changes. Crafting a precise conventional commit message that lists affected scope and changes requires re-reading the diff or recalling session objectives.

### Solution
A `commit-draft` subcommand that inspects the latest session for the current working directory, parses `latest_summary` and `file_line_tracker`, and generates a formatted Git commit message (or directly invokes `git commit -e -m`).

### Data Sources & DB Queries
- **`conversations_v2`**: Filtered by `key = <cwd>`, ordered by `updated_at DESC LIMIT 1`.
- **`value -> latest_summary`**: Serves as the commit body.
- **`value -> file_line_tracker`**: Identifies modified file modules/paths to infer commit scope (e.g., `feat(auth): ...`).
- **`value -> transcript`**: Extracts the initial user prompt as a draft commit subject line.

### CLI Design
```bash
# Preview generated commit message
kiro-sessionizer commit-draft

# Open Git commit editor pre-populated with the session draft
git commit -e -m "$(kiro-sessionizer commit-draft --raw)"
```

### Commit Output Example
```text
feat(auth): add JWT middleware and rate limiting

- Configured JWT verification middleware in src/auth/jwt.ts
- Implemented sliding window rate limiting in src/middleware/rate_limiter.ts
- Updated unit tests in tests/auth.test.ts

Generated from kiro-cli session: bbd5ad62-be7b-446b-8cd9-2025075d0852
```

---

## 3. Workspace File Restorer (`kiro-sessionizer restore`)

### Motivation
When resuming an older session or switching between tasks, developers must manually remember and reopen the files that were modified or discussed during that AI session.

### Solution
A `restore` subcommand (or interactive keybinding in the `fzf` picker) that parses `file_line_tracker` from a selected session and reopens those files in the developer's preferred editor (`$EDITOR`, VS Code `code`, Cursor `cursor`, or Vim).

### Data Sources & DB Queries
- **`value -> file_line_tracker`**: JSON object containing keys representing absolute or relative file paths accessed/edited in the session.
- Filter out non-existent files to ensure clean editor startup.

### CLI Design
```bash
# Reopen files touched in the most recent session for current directory
kiro-sessionizer restore

# Interactively pick a session and open its touched files in VS Code
kiro-sessionizer restore --editor code

# Keybinding integration in fzf picker:
# Pressing `ctrl-o` in `kiro-sessionizer` opens all session files in editor
```

---

## 4. Project History & Timeline Journal (`kiro-sessionizer journal`)

### Motivation
Over time, projects accumulate tens or hundreds of AI sessions. There is no high-level architectural timeline showing how a project evolved through AI collaboration over weeks or months.

### Solution
A `journal` subcommand that aggregates all historical sessions for a given project directory into a chronological development journal (`JOURNAL.md` or stdout), showing feature evolution, model choices, and architectural decisions over time.

### Data Sources & DB Queries
- **`conversations_v2` / `conversations`**: Filtered by `key = <project_path>`, sorted by `created_at ASC`.
- **`value -> history`**: Message count and timestamps.
- **`value -> latest_summary`**: High-level milestone summaries.
- **`value -> model_info`**: Models used (e.g., tracking evolution from Claude 3.5 Sonnet to Auto/Claude 3.7).

### CLI Design
```bash
# Display development timeline for current project
kiro-sessionizer journal

# Export project journal to Markdown file
kiro-sessionizer journal --output PROJECT_AI_JOURNAL.md
```

### Journal Output Example
```markdown
# Project AI Development Journal: /Users/dev/projects/api-service

### 2026-03-15 — Initial Setup & Schema Design
- **Session ID**: `a1b2c3d4` | **Model**: `claude-3.5-sonnet` | **Messages**: 18
- **Summary**: Scaffolding Node.js API with Express and Prisma ORM.

### 2026-04-01 — Authentication Implementation
- **Session ID**: `e5f6g7h8` | **Model**: `auto` | **Messages**: 32
- **Summary**: Implemented JWT authentication and password hashing logic.
```

---

## 5. Smart Session Pruning & Maintenance (`kiro-sessionizer prune`)

### Motivation
Because `kiro-cli` stores sessions indefinitely, SQLite databases can grow large with abandoned, empty, or single-turn test sessions. Manually deleting them one-by-one is tedious.

### Solution
A `prune` subcommand that identifies low-value sessions (e.g., 0-1 messages, older than X days, abandoned sessions with no tool calls) and allows dry-run inspection before batch deletion.

### Data Sources & DB Queries
- **`conversations_v2`**: Queries for `updated_at < threshold` and `LENGTH(value)` or parsed `len(history) <= 2`.
- Active process safety check (`get_active_sessions()`) to prevent deleting active lock-held sessions.

### CLI Design
```bash
# Dry run: see which sessions would be pruned (older than 30 days with <= 2 messages)
kiro-sessionizer prune --days 30 --min-messages 2 --dry-run

# Execute batch deletion with confirmation prompt
kiro-sessionizer prune --days 30 --min-messages 2
```

---

## Architecture & Integration Strategy

```
                          +------------------------+
                          | kiro-cli data.sqlite3  |
                          +-----------+------------+
                                      |
                                      v
                          +------------------------+
                          |   kiro_sessionizer.py  |
                          +-----------+------------+
                                      |
        +-------------------+---------+---------+-------------------+
        |                   |                   |                   |
        v                   v                   v                   v
+---------------+   +---------------+   +---------------+   +---------------+
|    report     |   | commit-draft  |   |    restore    |   | journal/prune |
| Standup/Stats |   | Git Commit Msg|   | Editor Launch |   | Maintenance   |
+---------------+   +---------------+   +---------------+   +---------------+
```

All 5 features reuse existing core primitives in `kiro_sessionizer.py`:
- Cross-version DB query logic (`conversations_v2` UNION `conversations`).
- Active session detection (`get_active_sessions()`).
- Safe JSON parsing and fallback error handling.

By extending `kiro-sessionizer` with these features, the tool evolves from a pure session finder into an indispensable **AI-assisted developer workflow hub**.
