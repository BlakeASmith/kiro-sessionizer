# kiro-cli Session Management Research

## Session Storage Overview
`kiro-cli` (formerly Amazon Q Developer CLI) uses a single SQLite database to persist all chat sessions across the entire system.

- **Database Path (macOS):** `~/Library/Application Support/kiro-cli/data.sqlite3`
- **Primary Table:** `conversations_v2`
- **Legacy Table:** `conversations` (from versions <= 1.13.x)

### `conversations_v2` Schema
| Column | Type | Description |
|--------|------|-------------|
| `key` | TEXT | Absolute path to the working directory. |
| `conversation_id` | TEXT | Unique UUID for the session. |
| `value` | TEXT | JSON blob of the session state. |
| `created_at` | INTEGER | Milliseconds since epoch. |
| `updated_at` | INTEGER | Milliseconds since epoch. |

**Primary Key:** `(key, conversation_id)`

---

## Session Resumption Logic
When `kiro-cli chat --resume` is executed, the following steps occur:

1. **Directory Identification:** The CLI identifies the current working directory (CWD).
2. **Database Query:** It queries the `conversations_v2` table for the row matching the CWD in the `key` column with the highest `updated_at` value.
3. **State Loading:** The JSON blob in the `value` column is parsed into a `ConversationState` object.
4. **Resumption:** The session UI is restored, and the history is displayed.

### The "Recent Session" Problem
Because `kiro-cli` always picks the row with the latest `updated_at` for the current directory, there is no native way to resume an arbitrary session from the command line unless it happens to be the most recent one in that specific directory.

---

## Technical Feasibility for `kiro-sessionizer`

### 1. Alternative Resume Methods
Investigation of the `ChatArgs` source code reveals that the `--resume` flag is a boolean. There is currently **no built-in argument** (e.g., `--resume-id <uuid>`) to specify a particular session via the command line.

The `--resume-picker` feature (likely a `kiro-cli` wrapper or a later closed-source addition) confirms that session selection is possible, but it is limited to sessions within the *current* directory.

### 2. The `updated_at` Modification Strategy
The most reliable way to force `kiro-cli` to open a specific session is to temporarily update its `updated_at` timestamp to a value higher than any other session in its directory.

#### Restoration Feasibility
It is technically feasible to restore the original `updated_at` timestamp after `kiro-cli` is launched.

**Proposed Workflow:**
1. **Record:** Fetch and store the original `updated_at` and `conversation_id` for the target session.
2. **Update:** Set the target session's `updated_at` to `current_time + 1000`.
3. **Execute:** Launch `kiro-cli chat --resume` in the target directory.
4. **Cleanup (Optional):** Once `kiro-cli` exits, the `updated_at` could be reverted.
    - *Note:* If the user adds new messages during the session, `kiro-cli` will automatically update `updated_at` to the actual finish time. Restoring the old timestamp might be undesirable if the user wants the session to remain at the top of their recent list.

### 3. Session Previewing
The `value` JSON blob contains a `transcript` array. This is the most efficient way to provide a preview in `fzf` without parsing the full message history.

```json
{
  "transcript": [
    "> User: How do I implement a global picker?",
    "Assistant: You can use SQLite to query sessions..."
  ]
}
```
