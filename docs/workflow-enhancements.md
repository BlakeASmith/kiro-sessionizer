# kiro-sessionizer Developer Workflow Enhancements

## Overview
The `kiro-cli` tool persists rich developer metadata during chat sessions in a local SQLite database (`data.sqlite3`). This document outlines five developer workflow enhancements built on top of this stored metadata. By leveraging fields like `file_line_tracker`, `latest_summary`, `transcript`, and `updated_at`, `kiro-sessionizer` can act as an intelligent workflow companion.

---

## 1. Workspace Restore (`restore`)
* **Problem:** When resuming a session or jumping back into an old project, developers often spend time manually locating and reopening the exact files they were editing or discussing.
* **DB Leveraged Data:** The `conversations_v2.value` JSON blob includes a `file_line_tracker` dictionary that tracks paths of files read/written during the session.
* **Proposed Enhancement:** A `restore` subcommand reads `file_line_tracker` keys, filters out non-existent files, and reopens them in the user's preferred editor (e.g., VS Code `code`, Cursor, Vim, or Nano).
* **Fuzzy Finder Integration:** Configured as a background action (`ctrl-o` keybinding) in the main interactive fuzzy finder, allowing developers to restore workspace files without closing the session browser.

---

## 2. Conventional Commit Draft (`commit-draft`)
* **Problem:** Writing descriptive, accurate Git commit messages after a long development session takes mental effort.
* **DB Leveraged Data:** The `latest_summary` contains a neat summary of the assistant's work, and the `file_line_tracker` contains paths of files that were modified.
* **Proposed Enhancement:** A `commit-draft` command retrieves the most recent session's summary and the list of affected files, and drafts a beautifully formatted conventional commit message body ready for copying or feeding directly into `git commit`.

---

## 3. Daily Standup Report Generator (`report`)
* **Problem:** Compiling standup notes ("What did I do yesterday?") can be tedious and prone to forgetfulness.
* **DB Leveraged Data:** Aggregates `updated_at` timestamps, project names, `latest_summary`, `history` message counts, and initial user queries across both v1 and v2 tables.
* **Proposed Enhancement:** A `report` subcommand that generates a formatted Markdown standup report for a specified timeframe (e.g., `--days 1`), grouping developer activity by project.

---

## 4. Chronological Project Journal (`journal`)
* **Problem:** Developers returning to a project after weeks away need to reconstruct the chronological narrative of what was built, why decisions were made, and what queries were run.
* **DB Leveraged Data:** Iterates chronologically through all sessions for a specific project directory (`key`), extracting the initial query and `latest_summary` of each session.
* **Proposed Enhancement:** A `journal` subcommand outputs a structured project history timeline. It defaults to the current working directory to easily review historical context of the current workspace.

---

## 5. Session Pruner (`prune`)
* **Problem:** Since sessions accumulate indefinitely without automatic cleanup, the database can grow large with short, accidental, or old experimental sessions.
* **DB Leveraged Data:** Analyzes `updated_at` timestamps and the length of the `history` array inside session JSON blobs.
* **Proposed Enhancement:** A `prune` subcommand that clears out inactive sessions older than a certain age (`--days 30`) that have fewer than a threshold of messages (`--min-messages 2`). Features a dry-run mode and an interactive safety confirmation.

---

## Summary of DB Mappings

| Enhancement | Primary DB Fields Used | Output/Action |
|-------------|-------------------------|---------------|
| `restore` | `file_line_tracker` | Reopens relevant files in preferred editor |
| `commit-draft` | `latest_summary`, `file_line_tracker` | Drafts a formatted conventional Git commit message |
| `report` | `updated_at`, `key`, `latest_summary`, `transcript` | Generates a Markdown daily/weekly standup report |
| `journal` | `key`, `updated_at`, `latest_summary`, `transcript` | Creates a chronological narrative log of a project's evolution |
| `prune` | `updated_at`, `history` length | Cleans up obsolete/empty sessions from the DB |
