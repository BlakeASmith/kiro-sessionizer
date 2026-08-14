#!/usr/bin/env python3
import sqlite3
import json
import os
import sys
import subprocess
from datetime import datetime
import re
import glob
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
    
    rows = []
    # Try querying v2
    try:
        cursor.execute("SELECT key, conversation_id, value, updated_at, 'v2' as source FROM conversations_v2")
        rows.extend(cursor.fetchall())
    except sqlite3.OperationalError:
        pass

    # Try querying legacy conversations
    try:
        cursor.execute("SELECT key, 'legacy' as conversation_id, value, 0 as updated_at, 'v1' as source FROM conversations")
        rows.extend(cursor.fetchall())
    except sqlite3.OperationalError:
        pass

    conn.close()
    
    # Sort rows by updated_at descending in python
    rows.sort(key=lambda r: r[3], reverse=True)

    sessions = []
    for row in rows:
        key, conv_id, value, updated_at, source = row
        try:
            data = json.loads(value)
            transcript = data.get("transcript", [])
            history = data.get("history", [])
            model_info = data.get("model_info", {})
            model = model_info.get("model_id", "auto") if isinstance(model_info, dict) else "auto"
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
        "--bind", f"ctrl-o:execute(python3 {__file__} restore {{9}} --key {{7}} --quiet)",
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
            try:
                cursor.execute("DELETE FROM conversations WHERE key = ?", (key,))
            except sqlite3.OperationalError:
                pass
        else:
            try:
                cursor.execute(
                    "DELETE FROM conversations_v2 WHERE conversation_id = ? AND key = ?",
                    (conv_id, key)
                )
            except sqlite3.OperationalError:
                pass

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
    try:
        cursor.execute(
            "UPDATE conversations_v2 SET updated_at = ? WHERE conversation_id = ? AND key = ?",
            (now_ms, session["id"], session["key"])
        )
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()

def run_preview(path_ansi, conv_id_ansi, pid_ansi, project_ansi):
    path = strip_ansi(path_ansi).strip()
    conv_id = strip_ansi(conv_id_ansi).strip()
    pid = strip_ansi(pid_ansi).strip()
    project = strip_ansi(project_ansi).strip()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    row = None
    if conv_id == "legacy":
        try:
            cursor.execute("SELECT value FROM conversations WHERE key = ?", (path,))
            row = cursor.fetchone()
        except sqlite3.OperationalError:
            pass
    else:
        try:
            cursor.execute(
                "SELECT value FROM conversations_v2 WHERE conversation_id = ? AND key = ?",
                (conv_id, path)
            )
            row = cursor.fetchone()
        except sqlite3.OperationalError:
            pass
    
    conn.close()
        
    if not row:
        print(f"No detailed data for session {conv_id} at {path}")
        return

    try:
        data = json.loads(row[0])
        model_info = data.get("model_info", {})
        model = model_info.get("model_id", "auto") if isinstance(model_info, dict) else "auto"
        history = data.get("history", [])
        summary = data.get("latest_summary")
        transcript = data.get("transcript", [])
        file_tracker = data.get("file_line_tracker", {}) or {}
        
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
            
        # Show files touched
        files_touched = [os.path.basename(f) for f in file_tracker.keys() if f]
        if files_touched:
            print(f"{BOLD}{CYAN}FILES TOUCHED:{RESET}")
            # Limit to top 10 unique files
            unique_files = sorted(list(set(files_touched)))[:10]
            for f in unique_files:
                print(f"  - {f}")
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

    # Sort rows by updated_at descending
    rows.sort(key=lambda r: r[3], reverse=True)

    dumped_count = 0
    for row in rows:
        key, conv_id, value, updated_at, source = row

        if specific_session_id and specific_session_id != conv_id:
            continue

        try:
            data = json.loads(value)
            transcript = data.get("transcript", [])
            model_info = data.get("model_info", {})
            model = model_info.get("model_id", "auto") if isinstance(model_info, dict) else "auto"
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
    sessions = get_sessions()
    if not sessions:
        print("No sessions found.")
        return

    total = len(sessions)
    models = {}
    projects = {}
    files_discussed = {}
    total_msgs = 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

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
            model = "unknown"
            if isinstance(model_info, dict):
                model = model_info.get("model_id", "unknown")
            models[model] = models.get(model, 0) + 1

            file_tracker = data.get("file_line_tracker", {}) or {}
            for filepath in file_tracker.keys():
                if filepath:
                    filename = os.path.basename(filepath)
                    files_discussed[filename] = files_discussed.get(filename, 0) + 1
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
        except: pass

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
        print(f"  {f:20} {count} times")


def search_sessions(query):
    all_sessions = get_sessions()
    results = []

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query_lower = query.lower()

    matches = set()
    try:
        cursor.execute("SELECT key, conversation_id FROM conversations_v2 WHERE value LIKE ?", (f"%{query}%",))
        matches.update(cursor.fetchall())
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("SELECT key, 'legacy' as conversation_id FROM conversations WHERE value LIKE ?", (f"%{query}%",))
        matches.update(cursor.fetchall())
    except sqlite3.OperationalError:
        pass

    for s in all_sessions:
        if (s["key"], s["id"]) not in matches:
            continue

        # Get full data to extract snippet
        if s["id"] == "legacy":
            try:
                cursor.execute("SELECT value FROM conversations WHERE key = ?", (s["key"],))
                row = cursor.fetchone()
            except sqlite3.OperationalError:
                row = None
        else:
            try:
                cursor.execute("SELECT value FROM conversations_v2 WHERE conversation_id = ? AND key = ?", (s["id"], s["key"]))
                row = cursor.fetchone()
            except sqlite3.OperationalError:
                row = None

        if not row: continue

        data = json.loads(row[0])
        transcript_text = " ".join(data.get("transcript", []))
        summary_text = data.get("latest_summary", "") or ""
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


def jump_to_project():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    rows = []
    try:
        cursor.execute("SELECT key, updated_at FROM conversations_v2")
        rows.extend(cursor.fetchall())
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("SELECT key, 0 as updated_at FROM conversations")
        rows.extend(cursor.fetchall())
    except sqlite3.OperationalError:
        pass

    conn.close()

    # Aggregate by key, taking max(updated_at)
    key_map = {}
    for key, updated_at in rows:
        if not key:
            continue
        if key not in key_map or updated_at > key_map[key]:
            key_map[key] = updated_at

    # Sort keys by maximum updated_at descending
    sorted_keys = sorted(key_map.items(), key=lambda x: x[1], reverse=True)

    # Filter by existing directories
    valid_paths = []
    for path, _ in sorted_keys:
        abs_path = os.path.abspath(path)
        if os.path.exists(abs_path) and os.path.isdir(abs_path):
            valid_paths.append(abs_path)

    if not valid_paths:
        print("No valid project directories found.", file=sys.stderr)
        return

    # Use fzf to select
    fzf_input = "\n".join(valid_paths)
    fzf_cmd = ["fzf", "--reverse", "--height", "40%", "--prompt", "Jump to project: "]
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
            selected_path = stdout.strip()
            print(f"cd {shlex.quote(selected_path)}")
    except FileNotFoundError:
        print("Error: 'fzf' is not installed.", file=sys.stderr)
        sys.exit(1)


def draft_commit():
    sessions = get_sessions()
    if not sessions:
        print("No sessions found.", file=sys.stderr)
        return

    # Pick the most recent session
    most_recent = sessions[0]

    # Read DB value
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    row = None
    if most_recent["id"] == "legacy":
        try:
            cursor.execute("SELECT value FROM conversations WHERE key = ?", (most_recent["key"],))
            row = cursor.fetchone()
        except sqlite3.OperationalError:
            pass
    else:
        try:
            cursor.execute(
                "SELECT value FROM conversations_v2 WHERE conversation_id = ? AND key = ?",
                (most_recent["id"], most_recent["key"])
            )
            row = cursor.fetchone()
        except sqlite3.OperationalError:
            pass
    conn.close()

    if not row:
        print("Could not retrieve session details.", file=sys.stderr)
        return

    try:
        data = json.loads(row[0])
        summary = data.get("latest_summary") or ""
        file_tracker = data.get("file_line_tracker", {}) or {}

        files_touched = list(file_tracker.keys())
        # Filter files that are relative/absolute paths
        files_touched = [os.path.basename(f) for f in files_touched if f]

        print(f"{BOLD}{BLUE}--- Drafted Commit Message ---{RESET}\n")

        # Build subject line
        subject = "work-in-progress: update from chat session"
        if summary:
            # Shorten summary to fit standard git subject line
            first_sentence = summary.split('.')[0].strip()
            if len(first_sentence) > 50:
                subject = first_sentence[:47] + "..."
            else:
                subject = first_sentence

        print(f"docs/feat/fix: {subject.lower()}")
        print()
        if summary:
            print(summary)
            print()

        if files_touched:
            print("Files affected:")
            for f in sorted(set(files_touched)):
                print(f"  - {f}")
        else:
            print("Files affected: none tracked")

    except Exception as e:
        print(f"Error drafting commit: {e}", file=sys.stderr)


def generate_report(days, project_filter=None):
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return

    now_ms = int(datetime.now().timestamp() * 1000)
    cutoff_ms = now_ms - (days * 24 * 60 * 60 * 1000)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    rows = []
    try:
        cursor.execute("SELECT key, conversation_id, value, updated_at FROM conversations_v2")
        rows.extend(cursor.fetchall())
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("SELECT key, 'legacy' as conversation_id, value, 0 as updated_at FROM conversations")
        rows.extend(cursor.fetchall())
    except sqlite3.OperationalError:
        pass

    conn.close()

    # Sort rows by updated_at descending
    rows.sort(key=lambda r: r[3], reverse=True)

    print(f"# Work Standup Report (Past {days} days)\n")

    count = 0
    for row in rows:
        key, conv_id, value, updated_at = row

        # Legacy updated_at is 0. If they want N days, skip legacy unless they ask for many days (e.g., 10000)
        if updated_at > 0 and updated_at < cutoff_ms:
            continue
        if updated_at == 0 and days < 10000:
            continue

        proj_name = os.path.basename(key)
        if project_filter and project_filter.lower() not in proj_name.lower() and project_filter.lower() not in key.lower():
            continue

        try:
            data = json.loads(value)
            history = data.get("history", [])
            transcript = data.get("transcript", [])
            summary = data.get("latest_summary")
            model_info = data.get("model_info", {})
            model = model_info.get("model_id", "auto") if isinstance(model_info, dict) else "auto"
            file_tracker = data.get("file_line_tracker", {}) or {}

            # First user prompt (forward iteration for initial query intent)
            first_user_msg = ""
            for line in transcript:
                if line.strip() and line.strip().startswith("> "):
                    first_user_msg = line.strip()[2:].strip()
                    break

            dt = datetime.fromtimestamp(updated_at / 1000) if updated_at > 0 else datetime.fromtimestamp(0)
            date_str = dt.strftime("%Y-%m-%d %H:%M") if updated_at > 0 else "Legacy Session"

            print(f"## [{proj_name}] {date_str}")
            print(f"- **Path:** `{key}`")
            print(f"- **Model:** `{model}` | **Messages:** {len(history)}")
            if first_user_msg:
                print(f"- **Initial Query:** *\"{first_user_msg}\"*")
            if summary:
                print(f"- **Summary:** {summary}")

            files = list(file_tracker.keys())
            if files:
                files_str = ", ".join([f"`{os.path.basename(f)}`" for f in files if f])
                print(f"- **Files touched:** {files_str}")
            print()
            count += 1
        except Exception:
            continue

    if count == 0:
        print("No activity found in the specified timeframe.")


def generate_journal(project_path=None):
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return

    if not project_path:
        project_path = os.getcwd()

    target_abs = os.path.abspath(project_path)
    proj_name = os.path.basename(target_abs)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # We query from both v2 and legacy tables separately then filter and sort
    rows = []
    try:
        cursor.execute("SELECT key, conversation_id, value, updated_at FROM conversations_v2 WHERE key = ?", (target_abs,))
        rows.extend(cursor.fetchall())
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("SELECT key, 'legacy' as conversation_id, value, 0 as updated_at FROM conversations WHERE key = ?", (target_abs,))
        rows.extend(cursor.fetchall())
    except sqlite3.OperationalError:
        pass

    conn.close()

    # Sort chronologically (updated_at ASC)
    rows.sort(key=lambda r: r[3])

    print(f"# Project Journal: {proj_name}")
    print(f"Path: `{target_abs}`\n")

    if not rows:
        print("No journal entries found for this project.")
        return

    for row in rows:
        key, conv_id, value, updated_at = row
        try:
            data = json.loads(value)
            history = data.get("history", [])
            transcript = data.get("transcript", [])
            summary = data.get("latest_summary")
            model_info = data.get("model_info", {})
            model = model_info.get("model_id", "auto") if isinstance(model_info, dict) else "auto"

            # Initial query (first USER message)
            first_user_msg = ""
            for line in transcript:
                if line.strip() and line.strip().startswith("> "):
                    first_user_msg = line.strip()[2:].strip()
                    break

            dt = datetime.fromtimestamp(updated_at / 1000) if updated_at > 0 else datetime.fromtimestamp(0)
            date_str = dt.strftime("%Y-%m-%d %H:%M") if updated_at > 0 else "Legacy Session"

            print(f"### {date_str} (ID: {conv_id[:8] if conv_id != 'legacy' else 'legacy'})")
            print(f"- **Model:** `{model}` | **Messages:** {len(history)}")
            if first_user_msg:
                print(f"- **First Query:** *\"{first_user_msg}\"*")
            if summary:
                print(f"- **Summary:** {summary}")
            print()
        except Exception:
            continue


def prune_sessions(days=30, min_messages=0, dry_run=True, force=False):
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return

    now_ms = int(datetime.now().timestamp() * 1000)
    cutoff_ms = now_ms - (days * 24 * 60 * 60 * 1000)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    rows = []
    try:
        cursor.execute("SELECT key, conversation_id, value, updated_at FROM conversations_v2")
        rows.extend(cursor.fetchall())
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("SELECT key, 'legacy' as conversation_id, value, 0 as updated_at FROM conversations")
        rows.extend(cursor.fetchall())
    except sqlite3.OperationalError:
        pass

    to_delete = []
    for row in rows:
        key, conv_id, value, updated_at = row
        try:
            data = json.loads(value)
            history = data.get("history", []) or []
            msg_count = len(history)

            # Treat legacy updated_at as 0 (Unix epoch)
            # Filter condition:
            # - If older than N days (updated_at < cutoff_ms)
            # - AND message count is <= min_messages
            is_old = (updated_at < cutoff_ms) if updated_at > 0 else True

            if is_old and msg_count <= min_messages:
                to_delete.append((conv_id, key, msg_count, updated_at))
        except Exception:
            continue

    if not to_delete:
        print("No sessions found matching the pruning criteria.")
        conn.close()
        return

    print(f"Found {len(to_delete)} sessions to prune:")
    for conv_id, key, msgs, updated_at in to_delete:
        dt = datetime.fromtimestamp(updated_at / 1000) if updated_at > 0 else datetime.fromtimestamp(0)
        date_str = dt.strftime("%Y-%m-%d")
        print(f"  - [{date_str}] Project: {os.path.basename(key)} ({msgs} msgs) ID: {conv_id}")

    if dry_run:
        print("\nThis was a DRY RUN. No changes were made. Use --apply to prune these sessions.")
        conn.close()
        return

    if not force:
        try:
            ans = input("\nAre you sure you want to delete these sessions? [y/N]: ").strip().lower()
            if ans not in ('y', 'yes'):
                print("Pruning cancelled.")
                conn.close()
                return
        except KeyboardInterrupt:
            print("\nPruning cancelled.")
            conn.close()
            return

    # Delete sessions
    active_map = get_active_sessions()
    deleted_count = 0
    for conv_id, key, _, _ in to_delete:
        # Kill active process if any
        pid = active_map.get(key)
        if pid:
            try:
                os.kill(pid, 15)  # SIGTERM
            except OSError:
                pass

        # Delete from DB
        if conv_id == "legacy":
            try:
                cursor.execute("DELETE FROM conversations WHERE key = ?", (key,))
            except sqlite3.OperationalError:
                pass
        else:
            try:
                cursor.execute(
                    "DELETE FROM conversations_v2 WHERE conversation_id = ? AND key = ?",
                    (conv_id, key)
                )
            except sqlite3.OperationalError:
                pass

        # Remove session files
        if conv_id != "legacy":
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


def restore_session_files(conv_id, key=None, editor=None, quiet=False):
    if not os.path.exists(DB_PATH):
        if not quiet:
            print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    row = None
    if conv_id == "legacy":
        if not key:
            if not quiet:
                print("Error: key is required for legacy session", file=sys.stderr)
            conn.close()
            return
        try:
            cursor.execute("SELECT value FROM conversations WHERE key = ?", (key,))
            row = cursor.fetchone()
        except sqlite3.OperationalError:
            pass
    else:
        # If no key, find the key from conversation_id
        if key:
            try:
                cursor.execute("SELECT value FROM conversations_v2 WHERE conversation_id = ? AND key = ?", (conv_id, key))
                row = cursor.fetchone()
            except sqlite3.OperationalError:
                pass
        else:
            try:
                cursor.execute("SELECT value, key FROM conversations_v2 WHERE conversation_id = ?", (conv_id,))
                row = cursor.fetchone()
            except sqlite3.OperationalError:
                pass

    conn.close()

    if not row:
        if not quiet:
            print(f"Session {conv_id} not found.", file=sys.stderr)
        return

    try:
        data = json.loads(row[0])
        file_tracker = data.get("file_line_tracker", {}) or {}
        # Get unique valid file paths
        files = []
        for filepath in file_tracker.keys():
            if filepath:
                # Resolve relative to the session's key (which is the directory path)
                session_dir = key if key else row[1] if len(row) > 1 else os.getcwd()
                abs_path = filepath if os.path.isabs(filepath) else os.path.abspath(os.path.join(session_dir, filepath))
                if os.path.exists(abs_path) and os.path.isfile(abs_path) and abs_path not in files:
                    files.append(abs_path)

        if not files:
            if not quiet:
                print("No valid files to restore.", file=sys.stderr)
            return

        # Determine editor
        selected_editor = editor or os.environ.get("EDITOR")
        if not selected_editor:
            # Detect available editors
            for candidate in ("code", "cursor", "vim", "nano"):
                if subprocess.call(["which", candidate], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                    selected_editor = candidate
                    break

        if not selected_editor:
            # Fallback to system default or just open/cat
            if sys.platform == "darwin":
                selected_editor = "open"
            elif sys.platform.startswith("linux"):
                selected_editor = "xdg-open"
            else:
                selected_editor = "more"

        if not quiet:
            print(f"Restoring {len(files)} files in {selected_editor}...")

        # Open files in the editor
        # For VS Code or Cursor, we can open all of them in one command
        if selected_editor in ("code", "cursor"):
            subprocess.Popen([selected_editor] + files, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # For terminal editors, run sequentially or open first
            # Since this might be run in fzf background (quiet), run without blocking
            for f in files:
                subprocess.Popen([selected_editor, f], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    except Exception as e:
        if not quiet:
            print(f"Error restoring files: {e}", file=sys.stderr)


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
    parser_backup = subparsers.add_parser("backup", help="Dump sessions to markdown files")
    parser_backup.add_argument("dest_dir", help="Directory to dump session markdown files into")
    parser_backup.add_argument("--session-id", help="Optional specific session ID to dump")

    parser_stats = subparsers.add_parser("stats", help="Show session statistics")

    parser_continue = subparsers.add_parser("continue", help="Resume the most recent session")

    parser_search = subparsers.add_parser("search", help="Search session transcripts")
    parser_search.add_argument("query", help="Search term")

    parser_jump = subparsers.add_parser("jump", help="Jump to a project directory")

    parser_commit_draft = subparsers.add_parser("commit-draft", help="Draft a Git commit message using recent session summary")

    parser_report = subparsers.add_parser("report", help="Generate a formatted Markdown standup report")
    parser_report.add_argument("--days", type=int, default=1, help="Number of days to look back")
    parser_report.add_argument("--project", help="Filter by project name")

    parser_journal = subparsers.add_parser("journal", help="Chronological summary of project history")
    parser_journal.add_argument("project_path", nargs="?", default=None, help="Path of the project")

    parser_prune = subparsers.add_parser("prune", help="Clean up old/empty sessions")
    parser_prune.add_argument("--days", type=int, default=30, help="Age threshold in days")
    parser_prune.add_argument("--min-messages", type=int, default=0, help="Minimum messages to preserve")
    parser_prune.add_argument("--apply", action="store_true", help="Apply deletions (default is dry-run)")
    parser_prune.add_argument("--force", action="store_true", help="Skip interactive confirmation prompt")

    parser_restore = subparsers.add_parser("restore", help="Restore workspace files")
    parser_restore.add_argument("conv_id")
    parser_restore.add_argument("--key", help="Project path/key")
    parser_restore.add_argument("--editor", help="Specific editor to open files")
    parser_restore.add_argument("--quiet", action="store_true", help="Quiet mode (no interactive prints)")

    args = parser.parse_args()

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

    if args.command == "jump":
        jump_to_project()
        return

    if args.command == "commit-draft":
        draft_commit()
        return

    if args.command == "report":
        generate_report(args.days, args.project)
        return

    if args.command == "journal":
        generate_journal(args.project_path)
        return

    if args.command == "prune":
        prune_sessions(days=args.days, min_messages=args.min_messages, dry_run=not args.apply, force=args.force)
        return

    if args.command == "restore":
        restore_session_files(args.conv_id, key=args.key, editor=args.editor, quiet=args.quiet)
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
