# kiro-cli Session Storage

## Overview

kiro-cli stores all session (conversation) state in a single SQLite database:

```
~/Library/Application Support/kiro-cli/data.sqlite3
```

## Database Tables

### `conversations_v2` — Primary session store

| Column            | Type    | Description                                      |
|-------------------|---------|--------------------------------------------------|
| `key`             | TEXT    | Working directory path (e.g. `/Users/blake/p/myproject`) |
| `conversation_id` | TEXT    | UUID uniquely identifying the conversation       |
| `value`           | TEXT    | Full session state as a JSON blob                |
| `created_at`      | INTEGER | Unix timestamp in milliseconds                   |
| `updated_at`      | INTEGER | Unix timestamp in milliseconds                   |

Primary key is `(key, conversation_id)`. Two indexes exist:
- `idx_conversations_v2_key_updated` on `(key, updated_at DESC)` — fast lookup of recent sessions per directory
- `idx_conversations_v2_updated_at` on `(updated_at DESC)` — fast lookup of most recently active sessions globally

Sessions are **scoped to the working directory** (`key`). Each directory can have multiple conversations, each with its own UUID.

### `conversations` — Legacy v1 store

Same concept as `conversations_v2` but with a simpler `(key, value)` schema. Populated during migration from an older format; new sessions go to `conversations_v2`.

### `state` — Global key/value store

Stores miscellaneous persistent state as `(key TEXT, value BLOB)` pairs. Examples of keys found in practice:

| Key | Description |
|-----|-------------|
| `telemetryClientId` | Stable anonymous telemetry UUID |
| `profile.Migrated` | Migration flag |
| `auth.idc.start-url` | IAM Identity Center start URL |
| `auth.idc.region` | IAM Identity Center region |
| `telemetry-cognito-credentials` | Short-lived Cognito credentials (JSON) |
| `desktop.versionAtPreviousLaunch` | Last-seen CLI version |
| `changelog.lastVersion` / `changelog.showCount` | Changelog display tracking |
| `welcomeAnnouncement.showCount` | Welcome screen display tracking |

### `auth_kv` — Auth token store

Simple `(key TEXT PRIMARY KEY, value TEXT)` table for authentication tokens and credentials.

### `history` — Shell command history

Stores shell command history (separate from chat sessions):

| Column | Description |
|--------|-------------|
| `command` | The shell command run |
| `shell` | Shell type (bash, zsh, etc.) |
| `pid` | Process ID |
| `session_id` | Shell session identifier |
| `cwd` | Working directory at time of command |
| `start_time` / `end_time` | Timestamps |
| `duration` | Execution duration |
| `exit_code` | Command exit code |
| `hostname` | Machine hostname |

### `migrations`

Tracks applied schema migrations with `(id, version, migration_time)`. As of writing, 9 migrations have been applied (versions 0–8).

---

## Session JSON Structure (`conversations_v2.value`)

Each row's `value` is a JSON object with the following top-level fields:

### `conversation_id`
`string` — UUID matching the row's `conversation_id` column.

### `history`
`array` — The full structured message history. Each entry is an object:
```json
{
  "user": {
    "content": { "Prompt": { "prompt": "user message text" } },
    "timestamp": "2026-04-04T12:13:58.641466-07:00",
    "additional_context": "",
    "env_context": {
      "env_state": {
        "operating_system": "macos",
        "current_working_directory": "/path/to/project",
        "environment_variables": []
      }
    },
    "images": null
  },
  "assistant": {
    "ToolUse": {
      "message_id": "<uuid>",
      "content": "assistant text response",
      "tool_uses": [ ... ]
    }
  },
  "request_metadata": { ... }
}
```

### `valid_history_range`
`[start, end]` integer pair — the slice of `history` that is currently active/valid (used when history is partially summarized or truncated).

### `transcript`
`array of strings` — A lightweight human-readable log of the conversation, alternating user and assistant turns. Tool use is noted inline (e.g. `"[Tool uses: fs_read]"`). Used for display purposes.

### `latest_summary`
`string | null` — A summarized version of older history, used when the context window would otherwise be exceeded. `null` if no summarization has occurred yet.

### `context_message_length`
`integer` — The token/character length of the injected context (system prompt, file context, etc.) for the most recent turn.

### `context_manager`
`object` — Configuration for what context files are injected into the conversation:
```json
{
  "max_context_files_size": 750000,
  "current_profile": "kiro_default",
  "paths": ["AmazonQ.md", "AGENTS.md", "README.md", ".kiro/skills/*/SKILL.md", "~/.kiro/skills/*/SKILL.md"],
  "hooks": {}
}
```

### `model_info`
`object` — The model selected for this conversation:
```json
{
  "model_name": "auto",
  "model_id": "auto",
  "description": "Models chosen by task for optimal usage and consistent quality",
  "context_window_tokens": 1000000,
  "rate_multiplier": 1.0,
  "rate_unit": "Credit"
}
```

### `tools`
`object` — Tool specifications available in this session, keyed by tool group (e.g. `"native___"`). Each group is an array of tool spec objects containing name, description, and input schema.

### `next_message`
`null | object` — A pending message to be sent on next continuation, if any.

### `file_line_tracker`
`object` — Tracks which file lines have been read/modified during the session (used for context management).

### MCP fields
| Field | Type | Description |
|-------|------|-------------|
| `mcp_enabled` | bool | Whether MCP (Model Context Protocol) is enabled |
| `mcp_last_checked` | array | Timestamp of last MCP server check |
| `mcp_server_versions` | object | Version info for connected MCP servers |
| `mcp_disabled_due_to_api_failure` | bool | Whether MCP was auto-disabled after a failure |

### `user_turn_metadata`
`object` — Metadata about the most recent request/response cycle:
```json
{
  "continuation_id": "<uuid>",
  "requests": [
    {
      "request_id": "<uuid>",
      "context_usage_percentage": 1.2091,
      "message_id": "<uuid>",
      "request_start_timestamp_ms": 1775330180714,
      "stream_end_timestamp_ms": 1775330184948,
      "time_to_first_chunk": { "secs": 2, "nanos": 61628417 },
      "time_between_chunks": [ ... ]
    }
  ],
  "usage_info": { ... }
}
```

---

## Key Behaviors

- **One DB, all sessions**: All projects share the single `data.sqlite3` file.
- **Directory-scoped**: The `key` column is the absolute path of the working directory when `kiro-cli chat` was launched. Switching directories creates a new session scope.
- **Multiple sessions per directory**: A directory can have many conversations, each with a unique `conversation_id`.
- **No automatic cleanup**: Sessions accumulate indefinitely; there is no observed TTL or pruning mechanism.
- **Summarization**: When a conversation grows long, older history can be summarized into `latest_summary` and the active window tracked via `valid_history_range`.
