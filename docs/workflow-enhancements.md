# kiro-cli: Leveraging SQLite Data for Advanced Developer Workflow Enhancements

## Executive Summary
The `kiro-sessionizer` utility serves as a global session picker and launcher for `kiro-cli` (formerly Amazon Q Developer CLI). While its current implementation provides crucial navigation and resume support, the local SQLite database used by `kiro-cli` contains a rich, untapped repository of developer intent, workspace contexts, command histories, and conversational states.

This document proposes **5 major workflow enhancements** designed to leverage this SQLite data directly. By transforming `kiro-sessionizer` from a simple launcher into an intelligent **Developer Productivity Suite**, we can drive significant gains in day-to-day coding activities—such as automatically restoring editor workspaces, drafting Git commits, auto-generating daily standup reports, branching/forking conversational threads, and auto-healing terminal command failures.

---

## 1. Contextual Data Landscape
To build these features, we tap into three distinct database schemas and folder contents maintained by `kiro-cli`:

### A. The Primary Store: `conversations_v2`
- **Key Fields**:
  - `key` (TEXT): Absolute working directory path of the project.
  - `conversation_id` (TEXT): UUID uniquely identifying the conversation.
  - `updated_at` (INTEGER): Timestamp of last activity in milliseconds.
  - `value` (TEXT / JSON blob): Contains the entire rich session state.

### B. Inside the Session JSON Blob (`conversations_v2.value`)
- `file_line_tracker` (JSON Object): Keys are absolute paths of files read/written during the session.
- `latest_summary` (JSON String): High-level conversational summary generated when context is compressed.
- `transcript` (JSON Array): Alternating list of user/assistant utterances including inline tool usage logs.
- `model_info` (JSON Object): Name and ID of the model used.
- `usage_info` (JSON Object): Token usage and cost metrics.

### C. The Command Store: `history`
- **Key Columns**:
  - `command` (TEXT): Shell command executed.
  - `cwd` (TEXT): Directory in which the command ran.
  - `exit_code` (INTEGER): Exit status of the command (0 for success, >0 for failure).
  - `start_time` / `end_time` (INTEGER): Millisecond timestamps.

---

## 2. Proposed Feature Designs

### Feature 1: Workspace Context Restore (`restore` / `workspace`)
#### Problem Statement
Resuming a CLI chat session in a terminal does not bring the developer's text editor back to the state it was in during that session. The developer must manually reopen the affected files one by one, losing valuable context and momentum.

#### The Data-Driven Solution
The JSON field `file_line_tracker` contains a record of every file the developer interacted with during the session. We can extract these paths and automatically open them in the developer’s preferred editor.

#### CLI Command Spec
```sh
kiro-sessionizer restore [session_id] [--editor <code|cursor|vim|nano>]
```

#### Python Architecture & Implementation Details
1. **Retrieve Paths**: Query the database to get the session's JSON value. Extract keys from `file_line_tracker`.
2. **Filter & Validate**: Verify that each extracted path exists on the local filesystem (omitting deleted or untracked temporary files).
3. **Editor Detection**: Prioritize specified `--editor` flags, falling back to environment variables (`$VISUAL`, `$EDITOR`), and then auto-detecting VS Code (`code`) or Cursor (`cursor`).
4. **Execution**: Launch the editor in the background. If no editor is available or specified, launch an interactive nested `fzf` file menu.

```python
def restore_session_workspace(session_id, editor_override=None):
    # Query row
    value_json = query_session_value(session_id)
    tracker = value_json.get("file_line_tracker", {})

    # Resolve and filter paths
    valid_paths = [path for path in tracker.keys() if os.path.exists(path)]

    if not valid_paths:
        print("No existing files tracked in this session.", file=sys.stderr)
        return

    # Determine editor
    editor = editor_override or os.environ.get("EDITOR") or "code"

    # Spawn editor process
    subprocess.Popen([editor] + valid_paths)
    print(f"Opened {len(valid_paths)} files in {editor}.")
```

#### fzf Integration
Integrate directly into the main `kiro-sessionizer` UI via a `ctrl-o` (Open Editor) keybinding:
```sh
--bind "ctrl-o:execute(python3 kiro_sessionizer.py restore {9})+reload(python3 kiro_sessionizer.py list)"
```

---

### Feature 2: Smart Conventional Commit Draft (`commit-draft`)
#### Problem Statement
Writing clear, descriptive commit messages conforming to Conventional Commits standard requires retrospection and tedious summarizing at the end of a session.

#### The Data-Driven Solution
`kiro-cli` already maintains a running text summarization (`latest_summary`) to manage its context window. Additionally, we know exactly what files were edited during the conversation. By combining these, we can automatically draft a structured commit message.

#### CLI Command Spec
```sh
kiro-sessionizer commit-draft [session_id] [--format <conventional|simple>]
```

#### Python Architecture & Implementation Details
1. **Analyze Files**: Parse `file_line_tracker` to identify the files modified. Infer a potential scope (e.g., using the directory name or file category).
2. **Retrieve Summary**: Read `latest_summary` or the most recent assistant turns.
3. **Draft Message**: Format as a Conventional Commit message.
4. **CLI Output**: Display the message in stdout for the user to pipe directly into `git commit -F -`, or print instructions to use it.

```python
def generate_commit_draft(session_id):
    value_json = query_session_value(session_id)
    summary = value_json.get("latest_summary") or "Work in progress"
    tracker = value_json.get("file_line_tracker", {})

    # Categorize modified files
    modified_files = [os.path.basename(p) for p in tracker.keys()]
    scope = os.path.basename(value_json.get("cwd", "")) or "app"

    commit_msg = f"feat({scope}): {summary.split('.')[0]}\n\n"
    commit_msg += f"{summary}\n\n"
    commit_msg += "Affected Files:\n"
    for f in modified_files:
        commit_msg += f"- {f}\n"

    return commit_msg
```

---

### Feature 3: Daily Standup & Project Journal Generator (`journal` & `report`)
#### Problem Statement
At the end of a sprint or daily standup, developers have to reconstruct what they worked on by scanning through commits, shell histories, or slack messages.

#### The Data-Driven Solution
Aggregating active sessions across projects and timeframes provides an instant, comprehensive activity report.

#### CLI Command Spec
```sh
# Generate standup report for the last N days
kiro-sessionizer report --days 1 [--project <project_path>]

# Generate a chronological historical journal for a project
kiro-sessionizer journal [<project_path>]
```

#### Python Architecture & Implementation Details
1. **Query Aggregator**: Query `conversations_v2` and legacy `conversations` where `updated_at` falls within the timeframe (`--days`).
2. **Extract Key Milestones**: For each session, extract the initial user query (the "problem") and the `latest_summary` (the "solution").
3. **Format Output**: Generate a highly polished Markdown report.

```python
def generate_standup_report(days=1, project_filter=None):
    cutoff = int((datetime.now().timestamp() - (days * 86400)) * 1000)
    sessions = fetch_sessions_after(cutoff, project_filter)

    print(f"# Standup Report - Past {days} Days\n")
    for s in sessions:
        project_name = os.path.basename(s['key'])
        print(f"## Project: {project_name}")
        print(f"- **Topic**: {s['first_query']}")
        print(f"- **Progress**: {s['summary']}")
        print(f"- **Files Modified**: {', '.join(s['files'])}\n")
```

---

### Feature 4: Session Forking & Prompt Branching (`fork`)
#### Problem Statement
When discussing complex architecture or refactoring, a developer might want to explore two different ideas (e.g., refactoring via inheritance vs. composition) using the same baseline conversation history. Currently, the developer has to start a completely new session from scratch, losing all previous context.

#### The Data-Driven Solution
Duplicate the database row in `conversations_v2` with a brand-new `conversation_id`, and write the corresponding metadata files in `~/.kiro/sessions/cli/` to create a parallel, independent chat path.

#### CLI Command Spec
```sh
kiro-sessionizer fork [session_id] --name <new_fork_name>
```

#### Python Architecture & Implementation Details
1. **Database Row Duplicate**:
   - Query the source row in `conversations_v2` using the source `conversation_id` and `key`.
   - Generate a new UUID for the forked session.
   - Deserialize the JSON state, update its internal `conversation_id` field, and serialize it back.
   - Insert the new row into `conversations_v2` with `created_at` and `updated_at` set to current time.
2. **Metadata Files Replication**:
   - Write `~/.kiro/sessions/cli/<new_uuid>.json` containing the matching `"cwd"`.
   - Let the next CLI session startup acquire the lock file gracefully.

```python
def fork_session(source_id, key, new_name):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT value FROM conversations_v2 WHERE conversation_id=? AND key=?", (source_id, key))
    row = cursor.fetchone()
    if not row:
         return False

    state = json.loads(row[0])
    new_uuid = str(uuid.uuid4())
    state["conversation_id"] = new_uuid
    state["latest_summary"] = f"[Forked from {new_name}] " + (state.get("latest_summary") or "")

    # Save back to DB
    now = int(datetime.now().timestamp() * 1000)
    cursor.execute(
        "INSERT INTO conversations_v2 (key, conversation_id, value, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (key, new_uuid, json.dumps(state), now, now)
    )
    conn.commit()
    conn.close()

    # Write metadata json file
    meta_path = os.path.join(SESSIONS_DIR, f"{new_uuid}.json")
    with open(meta_path, 'w') as f:
        json.dump({"cwd": key}, f)

    print(f"Successfully branched session to UUID: {new_uuid}")
```

---

### Feature 5: Terminal Failure Context Auto-Healer (`heal` / `debug`)
#### Problem Statement
When a build, test, or deployment command fails in the terminal, the developer has to manually copy-paste the terminal output into a new chat, wasting time formatting the query.

#### The Data-Driven Solution
The SQLite database contains a `history` table tracking all command executions, directory scopes, and exit codes. We can fetch the last executed command with an exit code > 0 in the current directory, retrieve the command, and feed it directly into `kiro-cli` with a prompt asking for an explanation and a fix.

#### CLI Command Spec
```sh
kiro-sessionizer heal [--cwd]
```

#### Python Architecture & Implementation Details
1. **Query Failed Command**: Select the most recent row from the `history` table where `cwd = ?` and `exit_code > 0` ordered by `end_time DESC`.
2. **Context Assembly**: Package the command name, shell type, and duration.
3. **Execute AI Query**: Construct an elegant prompt, e.g., `"The shell command '{command}' failed with exit code {exit_code}. Diagnose this failure and suggest a fix."`
4. **Trigger CLI Chat**: Automatically start/resume a `kiro-cli` chat using this prompt.

```python
def auto_heal_failure(current_cwd):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT command, exit_code
        FROM history
        WHERE cwd = ? AND exit_code > 0
        ORDER BY end_time DESC
        LIMIT 1
    """, (current_cwd,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        print("No recently failed shell command recorded in this directory.", file=sys.stderr)
        return

    failed_cmd, exit_code = row
    prompt = f"The terminal command '{failed_cmd}' failed in this directory with exit code {exit_code}. Can you diagnose why it failed and help me fix it?"

    # Trigger kiro-cli chat with the assembled prompt
    subprocess.run(["kiro-cli", "chat", prompt])
```

---

## Conclusion
By implementing these features, `kiro-sessionizer` evolves into an indispensable, context-aware command center. The integration of editor restore mechanisms (`restore`), automated commit drafting (`commit-draft`), chronological timeline logging (`report`), prompt forking (`fork`), and automated error analysis (`heal`) represents a massive force multiplier for developers working with `kiro-cli`.
