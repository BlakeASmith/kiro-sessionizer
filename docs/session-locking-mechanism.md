# kiro-cli Session Locking & Active State Detection

## Discovery
`kiro-cli` maintains a local session directory at `~/.kiro/sessions/cli/`. We have empirically verified that **only interactive sessions (TUI)** utilize this locking mechanism. One-off commands (e.g., using `--no-interactive`) do not create these files.

### Key Files
For a session with ID `bbd5ad62-be7b-446b-8cd9-2025075d0852`:
- **`[ID].lock`**: A JSON file (approx. 56 bytes) containing the process ID and start time.
  ```json
  {"pid": 49081, "started_at": "2026-04-04T19:42:47.774382Z"}
  ```
- **`[ID].json`**: A metadata file containing the `"cwd"` (current working directory), which serves as the link to the SQLite `conversations_v2` table.

## Reliability and Persistence
Our testing revealed that **lock files persist after a crash or force-kill (`kill -9`)**. Therefore, the mere existence of a `.lock` file is NOT a definitive indicator that a session is active.

### Reliable Detection Strategy
To accurately identify a "Running" session, `kiro-sessionizer` must perform the following validation:

1. **Scan**: Locate all `*.lock` files in `~/.kiro/sessions/cli/`.
2. **Extract**: Read the `pid` from the JSON content of the lock file.
3. **Verify Process**: Check if a process with that `pid` exists.
4. **Verify Identity**: Ensure the process command name contains `kiro-cli` (to prevent false positives from PID reuse).
5. **Map**: If the process is valid, read the corresponding `[ID].json` to find the `cwd`.
6. **Flag**: Match this `cwd` against the `key` column in the SQLite database to mark the session as active.

---

## Updated Proposed Feature: Active Session Indicators

### 1. Visual Markers in fzf
Sessions confirmed to be running via the strategy above will be flagged in the selection list.
- **Icon:** `●` (Green)
- **Label:** `[ACTIVE]`

### 2. Preview Window
The preview header will display `STATUS: ACTIVE (PID: 12345)` to warn the user that the session is currently locked by another process.

### 3. Handling Stale Locks
If a `.lock` file exists but the process is not running, the tool should treat the session as **Inactive** and may optionally offer to clean up the stale lock file.
