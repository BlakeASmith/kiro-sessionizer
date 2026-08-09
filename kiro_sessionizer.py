#!/usr/bin/env python3
import sqlite3
import json
import os
import sys
import subprocess
from datetime import datetime
import re
import glob
import shutil
import argparse
import shlex

DB_PATH = os.environ.get("KIRO_DB_PATH") or os.path.expanduser("~/Library/Application Support/kiro-cli/data.sqlite3")
SESSIONS_DIR = os.environ.get("KIRO_SESSIONS_DIR") or os.path.expanduser("~/.kiro/sessions/cli")

# ANSI Color Codes
BLUE = "\033[34m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
RED = "\033[31m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
RESET = "\033[0m"

def strip_ansi(text):
    return re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])').sub('', text)

def is_process_running(pid):
    """Check if a process with the given PID is running and is a kiro-cli process."""
    try:
        os.kill(pid, 0)
        cmd = ["ps", "-p", str(pid), "-o", "command="]
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return "kiro-cli" in output or "bun" in output
    except (OSError, subprocess.CalledProcessError):
        return False
def get_active_sessions():
    """Scan ~/.kiro/sessions/cli for active lock files AND check running processes."""
    active_paths = {}

    # Method 1: Lock files (most reliable for TUI)
    if os.path.exists(SESSIONS_DIR):
        lock_files = glob.glob(os.path.join(SESSIONS_DIR, "*.lock"))
        for lock_path in lock_files:
            try:
                with open(lock_path, 'r') as f:
                    lock_data = json.load(f)
                    pid = lock_data.get("pid")

                    if pid and is_process_running(pid):
                        json_path = lock_path.replace(".lock", ".json")
                        if os.path.exists(json_path):
                            with open(json_path, 'r') as jf:
                                json_data = json.load(jf)
                                cwd = json_data.get("cwd")
                                if cwd:
                                    active_paths[cwd] = pid
            except Exception:
                continue

    # Method 2: Fallback for non-interactive/hidden sessions (ps + lsof)
    try:
        # Get PIDs of all processes whose command line contains 'kiro-cli'
        ps_cmd = ["pgrep", "-f", "kiro-cli"]
        pids = subprocess.check_output(ps_cmd, text=True).strip().split('\n')

        for pid_str in pids:
            if not pid_str: continue
            pid = int(pid_str)
            if pid in active_paths.values(): continue # Already found via lock

            # Use lsof to find the CWD of the process
            lsof_cmd = ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"]
            lsof_out = subprocess.check_output(lsof_cmd, text=True)
            for line in lsof_out.split('\n'):
                if line.startswith('n'):
                    cwd = line[1:].strip()
                    if cwd and cwd not in active_paths:
                        active_paths[cwd] = pid
    except Exception:
        pass # Fallback failed, ignore

    return active_paths


def get_sessions():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    active_map = get_active_sessions()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    query = """
    SELECT key, conversation_id, value, updated_at, 'v2' as source
    FROM conversations_v2
    UNION ALL
    SELECT key, 'legacy' as conversation_id, value, 0 as updated_at, 'v1' as source
    FROM conversations
    ORDER BY updated_at DESC;
    """
    
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()
    
    sessions = []
    for row in rows:
        key, conv_id, value, updated_at, source = row
        try:
            data = json.loads(value)
            transcript = data.get("transcript", [])
            history = data.get("history", [])
            model_info = data.get("model_info", {})
            model = model_info.get("model_id", "auto")
            msg_count = len(history)
            
            # Extract first user message for better differentiation
            preview = ""
            first_user_msg = ""
            for line in reversed(transcript):
                if line.strip():
                    stripped = line.strip()
                    if stripped.startswith("> "):
                        first_user_msg = stripped[2:].strip().replace("\n", " ")[:120]
                    else:
                        preview = stripped.replace("\n", " ")[:100]
                    break
            
            dt = datetime.fromtimestamp(updated_at / 1000) if updated_at > 0 else datetime.now()
            date_str = dt.strftime("%Y-%m-%d %H:%M")
            
            project = os.path.basename(key)[:20]
            model_short = model.split(".")[-1][:16] if "." in model else model[:16]
            date_str = dt.strftime("%m-%d %H:%M")

            # Active indicator
            pid = active_map.get(key)
            status_icon = f"{GREEN}●{RESET}" if pid else " "

            # 1:icon, 2:proj, 3:date, 4:model, 5:msgs, 6:preview, 7:key, 8:pid, 9:conv_id
            display = (
                f"{status_icon}\t"
                f"{BOLD}{BLUE}{project}{RESET}\t"
                f"{YELLOW}{date_str}{RESET}\t"
                f"{CYAN}{model_short}{RESET}\t"
                f"{MAGENTA}{msg_count}{RESET}\t"
                f"{first_user_msg if first_user_msg else preview}\t"
                f"{GREEN}{key}{RESET}\t"
                f"{pid if pid else ''}\t"
                f"{conv_id}"
            )
            
            sessions.append({
                "key": key,
                "id": conv_id,
                "display": display,
                "source": source,
                "pid": pid
            })
        except Exception:
            continue
            
    return sessions

def is_fzf_tmux_supported():
    if not os.environ.get("TMUX"):
        return False
    try:
        result = subprocess.run(["fzf", "--help"], capture_output=True, text=True)
        return "--tmux" in result.stdout
    except Exception:
        return False

def get_session_files(path, conv_id):
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if conv_id == "legacy":
        cursor.execute("SELECT value FROM conversations WHERE key = ?", (path,))
    else:
        cursor.execute(
            "SELECT value FROM conversations_v2 WHERE conversation_id = ? AND key = ?",
            (conv_id, path)
        )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return []
    try:
        data = json.loads(row[0])
        tracker = data.get("file_line_tracker") or {}
        files = []
        if isinstance(tracker, dict):
            for fpath in tracker.keys():
                if not os.path.isabs(fpath):
                    abs_fpath = os.path.abspath(os.path.join(path, fpath))
                else:
                    abs_fpath = fpath
                if os.path.exists(abs_fpath) and os.path.isfile(abs_fpath):
                    files.append(abs_fpath)
        return sorted(list(set(files)))
    except Exception:
        return []

def restore_session_files(path, conv_id, editor=None):
    files = get_session_files(path, conv_id)
    if not files:
        print("No existing files found to restore for this session.", file=sys.stderr)
        return False

    if not editor:
        editor = os.environ.get("EDITOR")
        if not editor:
            for candidate in ["code", "cursor", "vim", "nano"]:
                if shutil.which(candidate):
                    editor = candidate
                    break

    if not editor:
        # Fall back to nested fzf file selection
        selected_files = nested_fzf_select_files(files)
        if not selected_files:
            print("No files selected or fzf aborted.", file=sys.stderr)
            return False
        files = selected_files
        # Use simple fallback editors
        for candidate in ["vim", "nano", "vi"]:
            if shutil.which(candidate):
                editor = candidate
                break

    if not editor:
        print("No editor detected to open files. Files:", file=sys.stderr)
        for f in files:
            print(f"  {f}", file=sys.stderr)
        return False

    try:
        if editor in ["code", "cursor"]:
            subprocess.Popen([editor] + files, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run([editor] + files)
        return True
    except Exception as e:
        print(f"Failed to launch editor {editor}: {e}", file=sys.stderr)
        return False

def nested_fzf_select_files(files):
    fzf_input = "\n".join(files)
    fzf_cmd = ["fzf", "--multi", "--prompt", "Select files to open > ", "--height", "40%", "--reverse"]
    try:
        proc = subprocess.Popen(fzf_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        stdout, _ = proc.communicate(input=fzf_input)
        if proc.returncode == 0 and stdout:
            return [line.strip() for line in stdout.strip().split('\n') if line.strip()]
    except Exception:
        pass
    return []

def select_session(sessions):
    fzf_input = "\n".join([s["display"] for s in sessions])
    
    fzf_cmd = ["fzf"]
    if is_fzf_tmux_supported():
        fzf_cmd.append("--tmux")

    fzf_cmd.extend([
        "--ansi",
        "--delimiter", "\t",
        "--with-nth", "1,2,3,4,5,6",
        "--header", f"\t{BOLD}{BLUE}Project{RESET}\t{YELLOW}Date{RESET}\t{CYAN}Model{RESET}\t{MAGENTA}Msgs{RESET}\tLast Message",
        "--reverse",
        "--height", "100%",
        "--preview-window", "bottom:80%:wrap",
        "--pointer", "▶",
        "--marker", "✓",
        "--multi",
        "--color", "header:italic:underline,pointer:bold:blue,marker:bold:green",
        "--preview", f"python3 {__file__} preview {{7}} {{9}} {{8}} {{2}}",
        "--bind", f"ctrl-x:execute(python3 {__file__} delete-multi {{+9}} --keys {{+7}})+reload(python3 {__file__} list),ctrl-o:execute-silent(python3 {__file__} restore {{7}} {{9}})",
        "--info", "inline",
        "--footer", f"{DIM}ctrl-x: delete  ctrl-o: restore files  tab: select multi{RESET}",
    ])

    try:
        process = subprocess.Popen(
            fzf_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True
        )
        stdout, _ = process.communicate(input=fzf_input)
        
        if process.returncode != 0 or not stdout:
            return None
            
        selected_lines = stdout.strip().split('\n')
        if not selected_lines:
            return None
            
        # Return the first one for the shell to cd into
        selected_display = selected_lines[0]
        stripped_selected = strip_ansi(selected_display)
        
        for s in sessions:
            if strip_ansi(s["display"]) == stripped_selected:
                return s
    except FileNotFoundError:
        print("Error: 'fzf' is not installed.", file=sys.stderr)
        sys.exit(1)
        
    return None

def delete_sessions(pairs):
    """pairs: list of (conv_id, key) tuples"""
    active_map = get_active_sessions()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    for conv_id, key in pairs:
        # Kill active process if any
        pid = active_map.get(key)
        if pid:
            try:
                os.kill(pid, 15)  # SIGTERM
            except OSError:
                pass

        # Delete from DB
        if conv_id == "legacy":
            cursor.execute("DELETE FROM conversations WHERE key = ?", (key,))
        else:
            cursor.execute(
                "DELETE FROM conversations_v2 WHERE conversation_id = ? AND key = ?",
                (conv_id, key)
            )

        # Remove session files
        if conv_id != "legacy":
            for ext in (".json", ".lock"):
                path = os.path.join(SESSIONS_DIR, conv_id + ext)
                try:
                    os.remove(path)
                except OSError:
                    pass

    conn.commit()
    conn.close()


def update_session(session):
    if session["source"] == "v1":
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    now_ms = int(datetime.now().timestamp() * 1000)
    cursor.execute(
        "UPDATE conversations_v2 SET updated_at = ? WHERE conversation_id = ? AND key = ?",
        (now_ms, session["id"], session["key"])
    )
    
    conn.commit()
    conn.close()

def run_preview(path_ansi, conv_id_ansi, pid_ansi, project_ansi):
    path = strip_ansi(path_ansi).strip()
    conv_id = strip_ansi(conv_id_ansi).strip()
    pid = strip_ansi(pid_ansi).strip()
    project = strip_ansi(project_ansi).strip()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if conv_id == "legacy":
        cursor.execute("SELECT value FROM conversations WHERE key = ?", (path,))
    else:
        cursor.execute(
            "SELECT value FROM conversations_v2 WHERE conversation_id = ? AND key = ?",
            (conv_id, path)
        )
    
    row = cursor.fetchone()
    conn.close()
        
    if not row:
        print(f"No detailed data for session {conv_id} at {path}")
        return

    try:
        data = json.loads(row[0])
        model = data.get("model_info", {}).get("model_id", "auto")
        history = data.get("history", [])
        summary = data.get("latest_summary")
        transcript = data.get("transcript", [])
        
        # Extract first user message for preview
        first_user_msg = ""
        for line in reversed(transcript):
            if line.strip() and line.strip().startswith("> "):
                first_user_msg = line.strip()[2:].strip().replace("\n", " ")[:150]
                break
        
        try:
            cols = os.get_terminal_size().columns
        except:
            cols = 80
            
        # Meta info header
        status_line = f" {BOLD}{RED}● ACTIVE (PID: {pid}){RESET}" if pid else ""
        print(f"{BOLD}{BLUE}PROJECT:{RESET} {project} {DIM}({path}){RESET}{status_line}")
        print(f"{BOLD}{CYAN}MODEL:  {RESET} {model} | {BOLD}{MAGENTA}MESSAGES:{RESET} {len(history)}")
        print(f"{DIM}ID:     {conv_id}{RESET}")
        print("-" * cols)
        
        # Show first user message prominently for differentiation
        if first_user_msg:
            print(f"{BOLD}{CYAN}FIRST QUERY:{RESET}")
            print(f"  {ITALIC}{first_user_msg}{RESET}")
            print("-" * cols)
        
        if pid:
            print(f"{BOLD}{RED}⚠️  WARNING: This session is currently active in another process.{RESET}")
            print(f"{DIM}Resuming may cause conflicts or fail if the lock is held.{RESET}")
            print("-" * cols)

        if summary:
            print(f"{BOLD}{YELLOW}SUMMARY:{RESET}")
            print(f"{ITALIC}{summary}{RESET}")
            print("-" * cols)
            
        print(f"{BOLD}CONVERSATION HISTORY:{RESET}\n")
        
        current_speaker = None
        for line in transcript:
            line = line.strip()
            if not line: continue
            
            if line.startswith("> "):
                if current_speaker != "USER":
                    print(f"{BOLD}{CYAN}USER 👤{RESET}")
                    current_speaker = "USER"
                print(f"  {line[2:].strip()}\n")
            elif line.startswith("[Tool uses:"):
                print(f"  {DIM}{ITALIC}{line}{RESET}")
            else:
                if current_speaker != "KIRO":
                    print(f"{BOLD}{GREEN}KIRO 🤖{RESET}")
                    current_speaker = "KIRO"
                content = line[10:].strip() if line.startswith("Assistant:") else line
                print(f"  {content}\n")
                    
    except Exception as e:
        print(f"Error parsing preview: {e}")


def dump_sessions(dest_dir, specific_session_id=None):
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query = """
    SELECT key, conversation_id, value, updated_at, 'v2' as source
    FROM conversations_v2
    UNION ALL
    SELECT key, 'legacy' as conversation_id, value, 0 as updated_at, 'v1' as source
    FROM conversations
    ORDER BY updated_at DESC;
    """

    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()

    dumped_count = 0
    for row in rows:
        key, conv_id, value, updated_at, source = row

        if specific_session_id and specific_session_id != conv_id:
            continue

        try:
            data = json.loads(value)
            transcript = data.get("transcript", [])
            model_info = data.get("model_info", {})
            model = model_info.get("model_id", "auto")
            dt = datetime.fromtimestamp(updated_at / 1000) if updated_at > 0 else datetime.now()
            date_str = dt.strftime("%Y-%m-%d %H:%M:%S")

            # Flatten structure: Use project name from key + conv_id for filename
            project = os.path.basename(key.rstrip(os.sep))
            target_dir = os.path.abspath(dest_dir)
            os.makedirs(target_dir, exist_ok=True)

            # Markdown file path (flat)
            file_name = f"{project}_{conv_id}.md"
            file_path = os.path.join(target_dir, file_name)

            with open(file_path, "w", encoding="utf-8") as f:
                # Write YAML frontmatter
                f.write("---\n")
                f.write(f"conversation_id: {conv_id}\n")
                f.write(f"path: {key}\n")
                f.write(f"model: {model}\n")
                f.write(f"updated_at: {date_str}\n")
                f.write("---\n\n")

                # Write transcript
                current_speaker = None
                for line in transcript:
                    line = line.strip()
                    if not line: continue

                    if line.startswith("> "):
                        if current_speaker != "USER":
                            f.write("\n## User\n\n")
                            current_speaker = "USER"
                        f.write(f"{line[2:].strip()}\n")
                    elif line.startswith("[Tool uses:"):
                        f.write(f"\n*{line}*\n")
                    else:
                        if current_speaker != "KIRO":
                            f.write("\n## Assistant\n\n")
                            current_speaker = "KIRO"
                        content = line[10:].strip() if line.startswith("Assistant:") else line
                        f.write(f"{content}\n")

            dumped_count += 1
            print(f"Dumped session {conv_id} to {file_path}", file=sys.stderr)

        except Exception as e:
            print(f"Error dumping session {conv_id}: {e}", file=sys.stderr)
            continue

    print(f"Successfully dumped {dumped_count} sessions.", file=sys.stderr)

def draft_git_commit():
    """Drafts a formatted Git commit message using the most recent session's summary and files."""
    sessions = get_sessions()
    if not sessions:
        print("No sessions found to draft a commit from.", file=sys.stderr)
        return

    # sessions are sorted by updated_at DESC, so sessions[0] is the most recent
    selected = sessions[0]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if selected["id"] == "legacy":
        cursor.execute("SELECT value FROM conversations WHERE key = ?", (selected["key"],))
    else:
        cursor.execute(
            "SELECT value FROM conversations_v2 WHERE conversation_id = ? AND key = ?",
            (selected["id"], selected["key"])
        )
    row = cursor.fetchone()
    conn.close()

    if not row:
        print("No session data found to draft a commit.", file=sys.stderr)
        return

    try:
        data = json.loads(row[0])
        summary = data.get("latest_summary") or ""
        tracker = data.get("file_line_tracker") or {}

        # Determine unique, short names of files touched
        files = []
        if isinstance(tracker, dict):
            for fpath in tracker.keys():
                files.append(os.path.basename(fpath))
        files = sorted(list(set(files)))

        project = os.path.basename(selected["key"])
        scope = project.lower() if project else "dev"

        # Conventional Commit structure
        subject = f"feat({scope}): work on session {selected['id'][:8]}"
        body = summary.strip() if summary else "Development work completed during session."

        draft = f"{subject}\n\n{body}\n"
        if files:
            draft += f"\nAffected files:\n" + "\n".join([f" - {f}" for f in files]) + "\n"

        print(draft)
    except Exception as e:
        print(f"Error drafting commit: {e}", file=sys.stderr)

def generate_journal(project_path=None):
    """Generates a chronological summary of a project's history."""
    if not project_path:
        project_path = os.getcwd()

    project_path = os.path.abspath(project_path)

    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Query both v1 and v2 conversations
    query = """
    SELECT key, conversation_id, value, updated_at, source
    FROM (
        SELECT key, conversation_id, value, updated_at, 'v2' as source FROM conversations_v2
        UNION ALL
        SELECT key, 'legacy' as conversation_id, value, 0 as updated_at, 'v1' as source FROM conversations
    )
    WHERE key = ?
    ORDER BY updated_at ASC;
    """

    cursor.execute(query, (project_path,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print(f"No session records found for project at {project_path}.", file=sys.stderr)
        return

    print(f"# Project Journal: {os.path.basename(project_path)}")
    print(f"Path: `{project_path}`\n")

    for row in rows:
        key, conv_id, value, updated_at, source = row
        try:
            data = json.loads(value)
            dt = datetime.fromtimestamp(updated_at / 1000) if updated_at > 0 else datetime.now()
            date_str = dt.strftime("%Y-%m-%d %H:%M:%S") if updated_at > 0 else "Legacy/Unknown Date"
            summary = data.get("latest_summary")
            transcript = data.get("transcript", [])

            # Extract first query
            first_user_msg = ""
            for line in transcript:
                if line.strip() and line.strip().startswith("> "):
                    first_user_msg = line.strip()[2:].strip()
                    break

            print(f"## Session {conv_id[:8]} - {date_str}")
            if first_user_msg:
                print(f"**First Query:** {first_user_msg}\n")
            if summary:
                print(f"**Summary:** {summary}\n")
            else:
                print("*No summary available for this session.*\n")
            print("---")
        except Exception:
            continue

def generate_report(days=7, project_filter=None):
    """Generates a formatted Markdown standup report by aggregating sessions over a specified timeframe."""
    sessions = get_sessions()
    if not sessions:
        print("No sessions found to generate a report from.")
        return

    cutoff = datetime.now().timestamp() - (days * 24 * 60 * 60)
    filtered_sessions = []

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    for s in sessions:
        if project_filter:
            p_name = os.path.basename(s["key"]).lower()
            if project_filter.lower() not in p_name and project_filter.lower() not in s["key"].lower():
                continue

        # Fetch detailed value to parse updated_at
        if s["id"] == "legacy":
            cursor.execute("SELECT value, 0 as updated_at FROM conversations WHERE key = ?", (s["key"],))
        else:
            cursor.execute(
                "SELECT value, updated_at FROM conversations_v2 WHERE conversation_id = ? AND key = ?",
                (s["id"], s["key"])
            )
        row = cursor.fetchone()
        if not row:
            continue

        value, updated_at = row
        updated_ts = (updated_at / 1000) if updated_at > 0 else 0
        if updated_ts > 0 and updated_ts < cutoff:
            continue

        filtered_sessions.append((s, value, updated_ts))

    conn.close()

    if not filtered_sessions:
        print(f"# Kiro Standup Report (Last {days} days)")
        print(f"\nNo active development sessions recorded in the last {days} days.")
        return

    print(f"# Kiro Standup Report (Last {days} days)")
    print(f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    for s, value, updated_ts in filtered_sessions:
        try:
            data = json.loads(value)
            project = os.path.basename(s["key"])
            dt = datetime.fromtimestamp(updated_ts) if updated_ts > 0 else datetime.now()
            date_str = dt.strftime("%Y-%m-%d %H:%M") if updated_ts > 0 else "Legacy"
            summary = data.get("latest_summary")
            history = data.get("history", [])
            model_info = data.get("model_info", {})
            model = model_info.get("model_id", "auto")

            tracker = data.get("file_line_tracker") or {}
            files = []
            if isinstance(tracker, dict):
                for fpath in tracker.keys():
                    files.append(os.path.basename(fpath))
            files = sorted(list(set(files)))

            print(f"### [{project}] Session {s['id'][:8]} ({date_str})")
            print(f"- **Model:** `{model}`")
            print(f"- **Messages:** {len(history)}")
            if files:
                print(f"- **Files touched:** " + ", ".join([f"`{f}`" for f in files]))
            if summary:
                print(f"- **Summary:** {summary}")
            else:
                # Fallback to first user query
                first_query = ""
                for line in data.get("transcript", []):
                    if line.strip() and line.strip().startswith("> "):
                        first_query = line.strip()[2:].strip()
                        break
                if first_query:
                    print(f"- **Initial query:** {first_query}")
            print()
        except Exception:
            continue

def prune_sessions(days=30, min_messages=0, apply=False, force=False):
    """Prunes older or empty sessions from both v1 and v2 tables."""
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return

    now_ms = int(datetime.now().timestamp() * 1000)
    cutoff_ms = now_ms - (days * 24 * 60 * 60 * 1000)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Determine eligible sessions
    try:
        cursor.execute("""
            SELECT key, conversation_id, value, updated_at, 'v2' as source FROM conversations_v2
            UNION ALL
            SELECT key, 'legacy' as conversation_id, value, 0 as updated_at, 'v1' as source FROM conversations
        """)
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        # Handle cases where one of the tables doesn't exist
        rows = []
        try:
            cursor.execute("SELECT key, conversation_id, value, updated_at, 'v2' as source FROM conversations_v2")
            rows.extend(cursor.fetchall())
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("SELECT key, 'legacy' as conversation_id, value, 0 as updated_at, 'v1' as source FROM conversations")
            rows.extend(cursor.fetchall())
        except sqlite3.OperationalError:
            pass

    to_delete = []
    for key, conv_id, value, updated_at, source in rows:
        try:
            data = json.loads(value)
            history = data.get("history") or []
            msg_count = len(history)

            # For legacy v1, treat updated_at as 0 (Unix epoch)
            eff_updated_at = updated_at if updated_at > 0 else 0

            if eff_updated_at < cutoff_ms and msg_count <= min_messages:
                to_delete.append((conv_id, key, source, eff_updated_at, msg_count))
        except Exception:
            continue

    if not to_delete:
        print("No sessions matched the pruning criteria.")
        conn.close()
        return

    print(f"Found {len(to_delete)} sessions eligible for pruning (older than {days} days, <= {min_messages} messages):")
    for conv_id, key, source, upd, msgs in to_delete:
        dt = datetime.fromtimestamp(upd / 1000) if upd > 0 else datetime.fromtimestamp(0)
        print(f" - [{source}] Session {conv_id[:8]} at {key} (Last active: {dt.strftime('%Y-%m-%d')}, Messages: {msgs})")

    if not apply:
        print("\n*** DRY RUN MODE *** Run with --apply to actually delete these sessions.")
        conn.close()
        return

    if not force:
        try:
            confirm = input("\nAre you sure you want to delete these sessions? [y/N]: ")
            if confirm.strip().lower() not in ["y", "yes"]:
                print("Pruning aborted.")
                conn.close()
                return
        except KeyboardInterrupt:
            print("\nPruning aborted.")
            conn.close()
            return

    # Execute deletions
    deleted_count = 0
    active_map = get_active_sessions()
    for conv_id, key, source, _, _ in to_delete:
        # Kill active processes if any
        pid = active_map.get(key)
        if pid:
            try:
                os.kill(pid, 15)
            except OSError:
                pass

        if source == "v1":
            cursor.execute("DELETE FROM conversations WHERE key = ?", (key,))
        else:
            cursor.execute("DELETE FROM conversations_v2 WHERE conversation_id = ? AND key = ?", (conv_id, key))

        # Remove local session files
        if source == "v2":
            for ext in (".json", ".lock"):
                path = os.path.join(SESSIONS_DIR, conv_id + ext)
                try:
                    os.remove(path)
                except OSError:
                    pass
        deleted_count += 1

    conn.commit()
    conn.close()
    print(f"Successfully pruned {deleted_count} sessions.")

def jump_to_project():
    """Lists unique project paths from the DB to CD/Jump into."""
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Query v2 first, then v1 to extract unique project paths
    # We must apply ORDER BY after UNION to avoid OperationalError in older sqlite versions
    try:
        cursor.execute("""
            SELECT key, MAX(updated_at) as max_upd
            FROM (
                SELECT key, updated_at FROM conversations_v2
                UNION ALL
                SELECT key, 0 as updated_at FROM conversations
            )
            GROUP BY key
        """)
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        rows = []
        try:
            cursor.execute("SELECT key, MAX(updated_at) as max_upd FROM conversations_v2 GROUP BY key")
            rows.extend(cursor.fetchall())
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("SELECT key, 0 as max_upd FROM conversations GROUP BY key")
            rows.extend(cursor.fetchall())
        except sqlite3.OperationalError:
            pass

    conn.close()

    # Sort in Python to ensure maximum compatibility and correctness
    sorted_rows = sorted(rows, key=lambda x: x[1] if x[1] is not None else 0, reverse=True)

    # Filter to only valid, existing directories
    valid_paths = []
    for row in sorted_rows:
        path = os.path.abspath(row[0])
        if os.path.exists(path) and os.path.isdir(path):
            valid_paths.append(path)

    if not valid_paths:
        print("No valid existing project paths found.", file=sys.stderr)
        return

    # Display using fzf
    fzf_input = "\n".join(valid_paths)
    fzf_cmd = ["fzf", "--prompt", "Jump to Project > ", "--height", "50%", "--reverse"]
    try:
        proc = subprocess.Popen(fzf_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        stdout, _ = proc.communicate(input=fzf_input)
        if proc.returncode == 0 and stdout:
            selected_path = stdout.strip()
            print(f"cd {shlex.quote(selected_path)}")
    except FileNotFoundError:
        print("Error: 'fzf' is not installed.", file=sys.stderr)

def show_stats():
    sessions = get_sessions()
    if not sessions:
        print("No sessions found.")
        return

    total = len(sessions)
    models = {}
    projects = {}
    files_tracker = {}
    total_msgs = 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query = """
    SELECT value FROM conversations_v2
    UNION ALL
    SELECT value FROM conversations
    """
    try:
        cursor.execute(query)
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        rows = []
        try:
            cursor.execute("SELECT value FROM conversations_v2")
            rows.extend(cursor.fetchall())
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("SELECT value FROM conversations")
            rows.extend(cursor.fetchall())
        except sqlite3.OperationalError:
            pass

    for row in rows:
        try:
            data = json.loads(row[0])
            model_info = data.get("model_info", {})
            if isinstance(model_info, dict):
                model = model_info.get("model_id", "unknown")
            else:
                model = "unknown"
            models[model] = models.get(model, 0) + 1

            # Extract files discussed from file_line_tracker
            tracker = data.get("file_line_tracker") or {}
            if isinstance(tracker, dict):
                for fpath in tracker.keys():
                    fname = os.path.basename(fpath)
                    files_tracker[fname] = files_tracker.get(fname, 0) + 1
        except Exception:
            continue
    conn.close()

    for s in sessions:
        project = os.path.basename(s["key"])
        projects[project] = projects.get(project, 0) + 1

        # Extract message count from display (it's the 5th tab-separated field)
        try:
            parts = strip_ansi(s["display"]).split('\t')
            total_msgs += int(parts[4])
        except Exception:
            pass

    print(f"{BOLD}{BLUE}--- Kiro Sessionizer Statistics ---{RESET}")
    print(f"{BOLD}Total Sessions:{RESET}  {total}")
    print(f"{BOLD}Total Messages:{RESET}  {total_msgs}")

    print(f"\n{BOLD}Top Projects:{RESET}")
    for p, count in sorted(projects.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {p:20} {count} sessions")

    print(f"\n{BOLD}Top Files Discussed:{RESET}")
    for f, count in sorted(files_tracker.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {f:20} discussed {count} times")

    print(f"\n{BOLD}Model Usage:{RESET}")
    for m, count in sorted(models.items(), key=lambda x: x[1], reverse=True):
        print(f"  {m:20} {count} sessions")

def search_sessions(query):
    all_sessions = get_sessions()
    results = []

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query_lower = query.lower()

    # Pre-filter using SQL LIKE for efficiency
    sql_query = """
    SELECT key, conversation_id FROM conversations_v2 WHERE value LIKE ?
    UNION ALL
    SELECT key, 'legacy' FROM conversations WHERE value LIKE ?
    """
    cursor.execute(sql_query, (f"%{query}%", f"%{query}%"))
    matches = set(cursor.fetchall())

    for s in all_sessions:
        if (s["key"], s["id"]) not in matches:
            continue

        # Get full data to extract snippet
        if s["id"] == "legacy":
            cursor.execute("SELECT value FROM conversations WHERE key = ?", (s["key"],))
        else:
            cursor.execute("SELECT value FROM conversations_v2 WHERE conversation_id = ? AND key = ?", (s["id"], s["key"]))

        row = cursor.fetchone()
        if not row: continue

        data = json.loads(row[0])
        transcript_text = " ".join(data.get("transcript", []))
        summary_text = data.get("latest_summary", "")
        full_text = transcript_text + " " + summary_text

        if query_lower in full_text.lower():
            # Find a snippet from original text
            idx = full_text.lower().find(query_lower)
            start = max(0, idx - 40)
            end = min(len(full_text), idx + 60)
            snippet = full_text[start:end].replace("\n", " ")

            # Update display to include snippet
            parts = s["display"].split('\t')
            # 1:icon, 2:proj, 3:date, 4:model, 5:msgs, 6:preview, 7:key, 8:pid, 9:conv_id
            parts[5] = f"{YELLOW}...{snippet}...{RESET}"
            s["display"] = "\t".join(parts)
            results.append(s)

    conn.close()
    return results

def main():
    parser = argparse.ArgumentParser(description="Global session resume support for kiro-cli")
    subparsers = parser.add_subparsers(dest="command")

    # Internal subcommands used by fzf
    parser_preview = subparsers.add_parser("preview", help=argparse.SUPPRESS)
    parser_preview.add_argument("path")
    parser_preview.add_argument("conv_id")
    parser_preview.add_argument("pid")
    parser_preview.add_argument("project", nargs="?", default="")

    parser_list = subparsers.add_parser("list", help=argparse.SUPPRESS)

    parser_restore = subparsers.add_parser("restore", help="Restore session files in editor")
    parser_restore.add_argument("path")
    parser_restore.add_argument("conv_id")
    parser_restore.add_argument("--editor", help="Specify editor to open files in")

    parser_delete = subparsers.add_parser("delete-multi", help=argparse.SUPPRESS)
    parser_delete.add_argument("ids_str")
    parser_delete.add_argument("--keys", required=True, dest="keys_str")

    # User subcommands
    parser_backup = subparsers.add_parser("backup", help="Dump sessions to markdown files")
    parser_backup.add_argument("dest_dir", help="Directory to dump session markdown files into")
    parser_backup.add_argument("--session-id", help="Optional specific session ID to dump")

    parser_stats = subparsers.add_parser("stats", help="Show session statistics")

    parser_prune = subparsers.add_parser("prune", help="Clean up old or empty sessions")
    parser_prune.add_argument("--days", type=int, default=30, help="Prune sessions older than this many days")
    parser_prune.add_argument("--min-messages", type=int, default=0, help="Prune sessions with this many or fewer messages")
    parser_prune.add_argument("--apply", action="store_true", help="Commit pruning changes to database (default is dry-run)")
    parser_prune.add_argument("--force", action="store_true", help="Skip confirmation prompt")

    parser_jump = subparsers.add_parser("jump", help="Quick-jump to a project directory from session history")

    parser_continue = subparsers.add_parser("continue", help="Resume the most recent session")

    parser_commit = subparsers.add_parser("commit-draft", help="Draft a Git commit message using recent session's summary")

    parser_journal = subparsers.add_parser("journal", help="Generate a chronological journal of a project's session history")
    parser_journal.add_argument("project_path", nargs="?", help="Path to project directory (defaults to CWD)")

    parser_report = subparsers.add_parser("report", help="Generate a Markdown standup report for recent sessions")
    parser_report.add_argument("--days", type=int, default=7, help="Number of days to look back")
    parser_report.add_argument("--project", help="Optional project name filter")

    parser_search = subparsers.add_parser("search", help="Search session transcripts")
    parser_search.add_argument("query", help="Search term")

    args = parser.parse_args()

    if args.command == "preview":
        run_preview(args.path, args.conv_id, args.pid, args.project)
        return

    if args.command == "list":
        sessions = get_sessions()
        print("\n".join([s["display"] for s in sessions]))
        return

    if args.command == "restore":
        path = strip_ansi(args.path).strip()
        conv_id = strip_ansi(args.conv_id).strip()
        restore_session_files(path, conv_id, args.editor)
        return

    if args.command == "delete-multi":
        try:
            conv_ids = shlex.split(args.ids_str)
            keys = shlex.split(args.keys_str)
            
            if len(conv_ids) == len(keys):
                pairs = list(zip(conv_ids, keys))
                delete_sessions(pairs)
        except ValueError:
            pass
        return

    if args.command == "backup":
        dump_sessions(args.dest_dir, args.session_id)
        return

    if args.command == "stats":
        show_stats()
        return

    if args.command == "prune":
        prune_sessions(args.days, args.min_messages, args.apply, args.force)
        return

    if args.command == "jump":
        jump_to_project()
        return

    if args.command == "commit-draft":
        draft_git_commit()
        return

    if args.command == "journal":
        generate_journal(args.project_path)
        return

    if args.command == "report":
        generate_report(args.days, args.project)
        return

    if args.command == "continue":
        sessions = get_sessions()
        if sessions:
            selected = sessions[0] # sessions are sorted by updated_at DESC
            update_session(selected)
            safe_key = shlex.quote(selected['key'])
            print(f"cd {safe_key} && kiro-cli chat --resume")
        else:
            print("No sessions found.", file=sys.stderr)
        return

    if args.command == "search":
        results = search_sessions(args.query)
        if not results:
            print(f"No results found for '{args.query}'", file=sys.stderr)
            return

        selected = select_session(results)
        if selected:
            update_session(selected)
            safe_key = shlex.quote(selected['key'])
            print(f"cd {safe_key} && kiro-cli chat --resume")
        return

    # Interactive picker mode
    sessions = get_sessions()
    if not sessions:
        print("No sessions found.", file=sys.stderr)
        return

    selected = select_session(sessions)
    if selected:
        if selected["pid"]:
            print(f"\n{BOLD}{YELLOW}Notice: Session is active (PID {selected['pid']}).{RESET}", file=sys.stderr)
            print(f"{DIM}Attempting to resume...{RESET}\n", file=sys.stderr)
            
        update_session(selected)
        safe_key = shlex.quote(selected['key'])
        print(f"cd {safe_key} && kiro-cli chat --resume")

if __name__ == "__main__":
    main()
