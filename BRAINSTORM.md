# Brainstorming Future Enhancements for `kiro-sessionizer`

By reading `kiro-cli`'s SQLite database (`conversations_v2`, `conversations`, `history`, `auth_kv`, etc.), we have access to rich historical data about developers' coding sessions, prompts, tools used, files touched, and active processes.

Below are several creative, workflow-enhancing features that can complement the existing interactive picker and `backup`/`search` subcommands.

---

## 1. Daily Standup & Activity Report Generator (`kiro-sessionizer report`)
* **Core Concept**: Automatically generate a structured markdown report of a developer's activities over a specific timeframe (e.g., today, yesterday, last 7 days).
* **How it leverages the DB**:
  - Filters rows in `conversations_v2` by `updated_at` timestamps.
  - Extracts modified/touched files from the `file_line_tracker` JSON field.
  - Pulls the `latest_summary` or first user query as the main objective of each session.
  - Aggregates model usage and total message count.
* **Workflow Value**: Eliminates the manual effort of remembering "What did I work on today?" for standups or compiling release/pull-request descriptions.

---

## 2. Git Commit Draft Generator (`kiro-sessionizer git-draft`)
* **Core Concept**: Draft a rich, descriptive git commit message based on the current or most recent `kiro-cli` session's transcript and touched files.
* **How it leverages the DB**:
  - Fetches the current session state based on the current working directory.
  - Reads `latest_summary` and the list of unique files modified from `file_line_tracker`.
  - Generates a commit message structure:
    ```
    feat(project): summary of the session goals

    - Updated file_a.py
    - Modified file_b.js

    Session Summary: [Insert summary from DB]
    ```
* **Workflow Value**: Boosts commit hygiene by ensuring commit messages are precise, context-aware, and aligned with what the developer and assistant actually achieved.

---

## 3. Session Workspace Restorer / Editor Launcher (`kiro-sessionizer restore`)
* **Core Concept**: Selecting a session doesn't just navigate you to its working directory, but also opens all the files touched in that session in your favorite editor (Cursor, VS Code, Vim, etc.).
* **How it leverages the DB**:
  - Parses `file_line_tracker` to get the list of active/touched file paths.
  - Filters out files that no longer exist on disk.
  - Executes a command like `code file1.py file2.js` or `cursor ...`.
* **Workflow Value**: Seamless workspace transitions. When resuming a session, you can pick up exactly where you left off, with all relevant context files instantly opened.

---

## 4. Smart Pruning & Session Health Analyzer (`kiro-sessionizer prune`)
* **Core Concept**: Identify and clean up stale, empty, or orphaned sessions to save space and keep the workspace tidy.
* **How it leverages the DB**:
  - Scans `conversations_v2` and looks for sessions with:
    - 0 or 1 messages (abandoned/accidental sessions).
    - No `latest_summary` and older than 30 days.
  - Allows interactive multi-select to delete them in bulk, or safe auto-prune.
* **Workflow Value**: Keeps the global session picker fast, responsive, and free of clutter.

---

## 5. Shell Command History Integrator (`kiro-sessionizer history`)
* **Core Concept**: Correlate shell command history from the `history` DB table with chat sessions.
* **How it leverages the DB**:
  - Merges `conversations_v2` session updates with the `history` table based on `cwd` and overlapping timestamps.
  - Lists the exact shell commands executed during a specific chat session in the preview window.
* **Workflow Value**: Helps the developer understand the practical commands that were run to test/compile the code proposed by the assistant during that session.

---

## 6. Context Token & Budget Estimator (`kiro-sessionizer metrics`)
* **Core Concept**: Show analytics on context window usage, token usage percentage, and LLM model utilization trends.
* **How it leverages the DB**:
  - Parses `user_turn_metadata` (e.g., `context_usage_percentage`, `usage_info`) and `model_info`.
  - Visualizes token usage trends and alerts developers when a session's history is getting close to the model's context limit, suggesting starting a fresh session.
* **Workflow Value**: Saves credits/costs and ensures optimal model speed and quality by avoiding unnecessarily bloated context windows.
