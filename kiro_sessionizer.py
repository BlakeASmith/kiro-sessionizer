#!/usr/bin/env python3
import sqlite3
import json
import os
import sys
import subprocess
from datetime import datetime
import re
import glob

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
        return []

    active_map = get_active_sessions()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
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

    conn.close()
    
    rows.sort(key=lambda x: x[3], reverse=True)

    sessions = []
    for row in rows:
        key, conv_id, value, updated_at, source = row
        try:
            data = json.loads(value)
            transcript = data.get("transcript", [])
            history = data.get("history", [])
            model_info = data.get("model_info", {})
            model = "auto"
            if isinstance(model_info, dict):
                model = model_info.get("model_id", "auto")
            elif isinstance(model_info, str):
                model = model_info
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
                "pid": pid,
                "updated_at": updated_at,
                "value": value
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
        "--bind", f"ctrl-x:execute(python3 {__file__} delete-multi {{+9}} --keys {{+7}})+reload(python3 {__file__} list)",
        "--bind", f"ctrl-o:execute(python3 {__file__} restore {{9}} --key {{7}})+reload(python3 {__file__} list)",
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


def jump_to_project():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    project_paths = {}

    try:
        cursor.execute("SELECT key, updated_at FROM conversations_v2")
        for key, updated_at in cursor.fetchall():
            if key:
                project_paths[key] = max(project_paths.get(key, 0), updated_at or 0)
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("SELECT key FROM conversations")
        for (key,) in cursor.fetchall():
            if key:
                project_paths[key] = max(project_paths.get(key, 0), 0)
    except sqlite3.OperationalError:
        pass

    conn.close()

    if not project_paths:
        print("No project directories found.", file=sys.stderr)
        return

    valid_paths = []
    for path, ts in project_paths.items():
        abs_path = os.path.abspath(path)
        if os.path.exists(abs_path):
            valid_paths.append((abs_path, ts))

    valid_paths.sort(key=lambda x: x[1], reverse=True)

    if not valid_paths:
        print("No existing project directories found.", file=sys.stderr)
        return

    fzf_lines = []
    for path, _ in valid_paths:
        proj_name = os.path.basename(path)
        fzf_lines.append(f"{BOLD}{BLUE}{proj_name}{RESET}\t{path}")

    fzf_input = "\n".join(fzf_lines)

    fzf_cmd = ["fzf", "--ansi", "--delimiter", "\t", "--with-nth", "1,2", "--header", "Select project directory to jump to"]
    if is_fzf_tmux_supported():
        fzf_cmd.append("--tmux")

    try:
        process = subprocess.Popen(
            fzf_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True
        )
        stdout, _ = process.communicate(input=fzf_input)

        if process.returncode == 0 and stdout:
            selected_line = stdout.strip()
            parts = selected_line.split("\t")
            if len(parts) >= 2:
                target_path = strip_ansi(parts[1]).strip()
                print(f"cd {shlex.quote(target_path)}")
    except FileNotFoundError:
        print("Error: 'fzf' is not installed.", file=sys.stderr)

def generate_journal(project_path=None):
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return

    if not project_path:
        project_path = os.getcwd()

    abs_project_path = os.path.abspath(project_path)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    rows = []

    try:
        cursor.execute(
            "SELECT value, updated_at FROM conversations_v2 WHERE key = ?",
            (abs_project_path,)
        )
        rows.extend([(row[0], row[1]) for row in cursor.fetchall()])
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute(
            "SELECT value, 0 as updated_at FROM conversations WHERE key = ?",
            (abs_project_path,)
        )
        rows.extend([(row[0], row[1]) for row in cursor.fetchall()])
    except sqlite3.OperationalError:
        pass

    conn.close()

    if not rows:
        print(f"No sessions found for project: {abs_project_path}")
        return

    rows.sort(key=lambda x: x[1])

    print(f"{BOLD}{BLUE}--- Project History Journal: {os.path.basename(abs_project_path)} ---{RESET}")
    print(f"{DIM}Path: {abs_project_path}{RESET}\n")

    for idx, (value, updated_at) in enumerate(rows, 1):
        try:
            data = json.loads(value)
            transcript = data.get("transcript", [])
            summary = data.get("latest_summary")

            first_query = ""
            for line in transcript:
                line_strip = line.strip()
                if line_strip.startswith("> "):
                    first_query = line_strip[2:].strip()
                    break

            dt = datetime.fromtimestamp(updated_at / 1000) if updated_at > 0 else datetime.fromtimestamp(0)
            date_str = dt.strftime("%Y-%m-%d %H:%M") if updated_at > 0 else "Legacy/Unknown"

            print(f"{BOLD}{GREEN}Session #{idx} [{date_str}]{RESET}")
            if first_query:
                print(f"  {BOLD}First Query:{RESET} {first_query[:100]}...")
            if summary:
                print(f"  {BOLD}Summary:{RESET} {summary}")
            else:
                preview = ""
                for line in reversed(transcript):
                    if line.strip():
                        preview = line.strip().replace("\n", " ")[:100]
                        break
                if preview:
                    print(f"  {BOLD}Preview:{RESET} {preview}")
            print("-" * 40)
        except Exception:
            continue

def prune_sessions(days, min_messages, apply_deletions, force):
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return

    now_ms = int(datetime.now().timestamp() * 1000)
    cutoff_ms = now_ms - (days * 24 * 60 * 60 * 1000)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

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
    for row in rows:
        key, conv_id, value, updated_at, source = row
        try:
            data = json.loads(value)
            history = data.get("history", [])
            msg_count = len(history)

            ts = updated_at if updated_at > 0 else 0

            if ts <= cutoff_ms and msg_count < min_messages:
                dt = datetime.fromtimestamp(ts / 1000) if ts > 0 else datetime.fromtimestamp(0)
                date_str = dt.strftime("%Y-%m-%d %H:%M")
                project = os.path.basename(key)
                to_delete.append((conv_id, key, source, project, date_str, msg_count))
        except Exception:
            continue

    if not to_delete:
        print("No sessions matched the pruning criteria.", file=sys.stderr)
        conn.close()
        return

    print(f"{BOLD}{YELLOW}Found {len(to_delete)} sessions to prune:{RESET}")
    for conv_id, key, source, project, date_str, msg_count in to_delete:
        print(f"  - {BOLD}{BLUE}{project}{RESET} ({date_str}, {msg_count} msgs, ID: {conv_id})")

    if not apply_deletions:
        print(f"\n{BOLD}{CYAN}DRY RUN ONLY. Use --apply to execute deletions.{RESET}")
        conn.close()
        return

    if not force:
        try:
            answer = input("\nAre you sure you want to delete these sessions? [y/N]: ").strip().lower()
            if answer not in ['y', 'yes']:
                print("Aborted.", file=sys.stderr)
                conn.close()
                return
        except KeyboardInterrupt:
            print("\nAborted.", file=sys.stderr)
            conn.close()
            return

    active_map = get_active_sessions()
    for conv_id, key, source, _, _, _ in to_delete:
        pid = active_map.get(key)
        if pid:
            try:
                os.kill(pid, 15)
            except OSError:
                pass

        if source == "v1":
            cursor.execute("DELETE FROM conversations WHERE key = ?", (key,))
        else:
            cursor.execute(
                "DELETE FROM conversations_v2 WHERE conversation_id = ? AND key = ?",
                (conv_id, key)
            )

        if source == "v2":
            for ext in (".json", ".lock"):
                path = os.path.join(SESSIONS_DIR, conv_id + ext)
                try:
                    os.remove(path)
                except OSError:
                    pass

    conn.commit()
    conn.close()
    print(f"\nSuccessfully pruned {len(to_delete)} sessions.", file=sys.stderr)

def generate_report(days, project_filter=None):
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return

    sessions = get_sessions()
    if not sessions:
        print("No sessions found.")
        return

    now_ms = int(datetime.now().timestamp() * 1000)
    cutoff_ms = now_ms - (days * 24 * 60 * 60 * 1000)

    report_sessions = []
    for s in sessions:
        ts = s.get("updated_at", 0)
        if ts < cutoff_ms:
            continue

        if project_filter:
            project_name = os.path.basename(s["key"])
            if project_filter.lower() not in project_name.lower() and project_filter.lower() not in s["key"].lower():
                continue

        report_sessions.append(s)

    if not report_sessions:
        print(f"No sessions found in the past {days} days matching filter.")
        return

    print(f"# Kiro Sessionizer Daily Standup Report (Past {days} days)")
    print(f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    by_project = {}
    for s in report_sessions:
        proj = os.path.basename(s["key"])
        if proj not in by_project:
            by_project[proj] = []
        by_project[proj].append(s)

    for proj, sess_list in by_project.items():
        print(f"## Project: {proj}")
        print(f"Path: `{sess_list[0]['key']}`\n")

        for idx, s in enumerate(sess_list, 1):
            try:
                data = json.loads(s["value"])
                dt = datetime.fromtimestamp(s["updated_at"] / 1000) if s["updated_at"] > 0 else datetime.now()
                date_str = dt.strftime("%Y-%m-%d %H:%M")

                model_info = data.get("model_info", {})
                model = model_info.get("model_id", "auto") if isinstance(model_info, dict) else "auto"
                history = data.get("history", [])
                msg_count = len(history)
                summary = data.get("latest_summary")

                transcript = data.get("transcript", [])
                first_query = ""
                for line in transcript:
                    line_strip = line.strip()
                    if line_strip.startswith("> "):
                        first_query = line_strip[2:].strip()
                        break

                tracker = data.get("file_line_tracker", {})
                touched_files = []
                if isinstance(tracker, dict):
                    touched_files = list(tracker.keys())

                print(f"### Session {idx} ({date_str})")
                print(f"- **Model:** `{model}`")
                print(f"- **Message Count:** {msg_count}")
                if first_query:
                    print(f"- **Initial Query:** *{first_query}*")
                if summary:
                    print(f"- **Latest Summary:** *{summary}*")
                if touched_files:
                    print(f"- **Files Touched:**")
                    for tf in touched_files[:10]:
                        print(f"  - `{tf}`")
                    if len(touched_files) > 10:
                        print(f"  - *and {len(touched_files) - 10} more files...*")
                print()
            except Exception:
                continue

def draft_commit():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return

    sessions = get_sessions()
    if not sessions:
        print("No sessions found.", file=sys.stderr)
        return

    most_recent = sessions[0]
    try:
        data = json.loads(most_recent["value"])
        summary = data.get("latest_summary")
        tracker = data.get("file_line_tracker", {})
        touched_files = []
        if isinstance(tracker, dict):
            touched_files = list(tracker.keys())

        project_name = os.path.basename(most_recent["key"])

        title = f"feat({project_name.lower()}): update from session {most_recent['id'][:8]}"
        body = summary or "Development and updates in work session."

        print(f"{BOLD}{GREEN}Drafted Git Commit Message:{RESET}\n")
        print(title)
        print()
        print(body)
        if touched_files:
            print()
            print("Affected Files:")
            for tf in touched_files:
                print(f"- {tf}")
    except Exception as e:
        print(f"Error drafting commit: {e}", file=sys.stderr)

def restore_session_files(conv_id, key, editor_arg=None):
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if conv_id == "legacy":
        cursor.execute("SELECT value FROM conversations WHERE key = ?", (key,))
    else:
        cursor.execute(
            "SELECT value FROM conversations_v2 WHERE conversation_id = ? AND key = ?",
            (conv_id, key)
        )

    row = cursor.fetchone()
    conn.close()

    if not row:
        print(f"Error: Session {conv_id} not found.", file=sys.stderr)
        return

    try:
        data = json.loads(row[0])
        tracker = data.get("file_line_tracker", {})
        if not tracker or not isinstance(tracker, dict):
            print("No files tracked in this session.", file=sys.stderr)
            return

        paths = []
        for path in tracker.keys():
            abs_path = os.path.abspath(os.path.join(key, path)) if not os.path.isabs(path) else path
            if os.path.exists(abs_path):
                paths.append(abs_path)

        if not paths:
            print("No existing files tracked in this session.", file=sys.stderr)
            return

        editor = editor_arg or os.environ.get("EDITOR") or os.environ.get("VISUAL")

        if not editor:
            for candidate in ["code", "cursor", "subl", "vim", "nano"]:
                if subprocess.run(["which", candidate], capture_output=True).returncode == 0:
                    editor = candidate
                    break

        if not editor:
            editor = "nano"

        is_gui_editor = editor in ["code", "cursor", "subl"]

        if len(paths) > 1:
            try:
                fzf_input = "\n".join(paths)
                fzf_cmd = ["fzf", "-m", "--ansi", "--header", f"Select files to open in {editor} (Tab to multi-select)"]
                process = subprocess.Popen(
                    fzf_cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=sys.stderr,
                    text=True
                )
                stdout, _ = process.communicate(input=fzf_input)
                if process.returncode == 0 and stdout:
                    selected_paths = [p.strip() for p in stdout.strip().split("\n") if p.strip()]
                else:
                    selected_paths = []
            except FileNotFoundError:
                selected_paths = paths
        else:
            selected_paths = paths

        if not selected_paths:
            return

        print(f"Opening {len(selected_paths)} file(s) in {editor}...", file=sys.stderr)

        if is_gui_editor:
            subprocess.Popen([editor] + selected_paths, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run([editor] + selected_paths)

    except Exception as e:
        print(f"Error restoring files: {e}", file=sys.stderr)

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

import argparse
import shlex

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

def show_stats():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return

    sessions = get_sessions()
    if not sessions:
        print("No sessions found.")
        return

    total = len(sessions)
    models = {}
    projects = {}
    total_msgs = 0
    files_discussed = {}

    for s in sessions:
        project = os.path.basename(s["key"])
        projects[project] = projects.get(project, 0) + 1

        try:
            parts = strip_ansi(s["display"]).split('\t')
            total_msgs += int(parts[4])
        except Exception:
            pass

        try:
            data = json.loads(s["value"])
            model_info = data.get("model_info", {})
            model = "unknown"
            if isinstance(model_info, dict):
                model = model_info.get("model_id", "unknown")
            elif isinstance(model_info, str):
                model = model_info
            models[model] = models.get(model, 0) + 1

            tracker = data.get("file_line_tracker", {})
            if isinstance(tracker, dict):
                for filepath in tracker.keys():
                    filename = os.path.basename(filepath)
                    if filename:
                        files_discussed[filename] = files_discussed.get(filename, 0) + 1
        except Exception:
            continue

    print(f"{BOLD}{BLUE}--- Kiro Sessionizer Statistics ---{RESET}")
    print(f"{BOLD}Total Sessions:{RESET}  {total}")
    print(f"{BOLD}Total Messages:{RESET}  {total_msgs}")

    print(f"\n{BOLD}Top Projects:{RESET}")
    for p, count in sorted(projects.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {p:20} {count} sessions")

    print(f"\n{BOLD}Model Usage:{RESET}")
    for m, count in sorted(models.items(), key=lambda x: x[1], reverse=True):
        print(f"  {m:20} {count} sessions")

    print(f"\n{BOLD}Top Files Discussed:{RESET}")
    for f, count in sorted(files_discussed.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {f:20} {count} mentions")

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

    parser_delete = subparsers.add_parser("delete-multi", help=argparse.SUPPRESS)
    parser_delete.add_argument("ids_str")
    parser_delete.add_argument("--keys", required=True, dest="keys_str")

    # User subcommands
    parser_jump = subparsers.add_parser("jump", help="Jump to a project directory interactively")

    parser_journal = subparsers.add_parser("journal", help="Show chronological summary journal of a project")
    parser_journal.add_argument("project_path", nargs="?", help="Path to the project directory")

    parser_prune = subparsers.add_parser("prune", help="Prune old sessions from the database")
    parser_prune.add_argument("--days", type=int, default=30, help="Prune sessions older than this (default: 30)")
    parser_prune.add_argument("--min-messages", type=int, default=5, help="Prune sessions with fewer messages than this (default: 5)")
    parser_prune.add_argument("--apply", action="store_true", help="Apply deletions to database")
    parser_prune.add_argument("--force", action="store_true", help="Force deletion without prompt")

    parser_report = subparsers.add_parser("report", help="Generate a standup/work summary report")
    parser_report.add_argument("--days", type=int, default=1, help="Show sessions updated in the last N days (default: 1)")
    parser_report.add_argument("--project", help="Filter by project name")

    parser_commit = subparsers.add_parser("commit-draft", help="Draft a Git commit message from the most recent session")

    parser_restore = subparsers.add_parser("restore", help="Restore files touched in a session")
    parser_restore.add_argument("conv_id")
    parser_restore.add_argument("--key", required=True)
    parser_restore.add_argument("--editor", help="Specify editor to open files with")

    parser_backup = subparsers.add_parser("backup", help="Dump sessions to markdown files")
    parser_backup.add_argument("dest_dir", help="Directory to dump session markdown files into")
    parser_backup.add_argument("--session-id", help="Optional specific session ID to dump")

    parser_stats = subparsers.add_parser("stats", help="Show session statistics")

    parser_continue = subparsers.add_parser("continue", help="Resume the most recent session")

    parser_search = subparsers.add_parser("search", help="Search session transcripts")
    parser_search.add_argument("query", help="Search term")

    args = parser.parse_args()

    if args.command == "jump":
        jump_to_project()
        return

    if args.command == "journal":
        generate_journal(args.project_path)
        return

    if args.command == "prune":
        prune_sessions(args.days, args.min_messages, args.apply, args.force)
        return

    if args.command == "report":
        generate_report(args.days, args.project)
        return

    if args.command == "commit-draft":
        draft_commit()
        return

    if args.command == "restore":
        restore_session_files(args.conv_id, args.key, args.editor)
        return

    if args.command == "preview":
        run_preview(args.path, args.conv_id, args.pid, args.project)
        return

    if args.command == "list":
        sessions = get_sessions()
        print("\n".join([s["display"] for s in sessions]))
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
