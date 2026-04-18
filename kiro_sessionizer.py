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

def get_db_path():
    return os.environ.get("KIRO_DB_PATH") or os.path.expanduser("~/Library/Application Support/kiro-cli/data.sqlite3")

def get_sessions_dir():
    return os.environ.get("KIRO_SESSIONS_DIR") or os.path.expanduser("~/.kiro/sessions/cli")

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
    sessions_dir = get_sessions_dir()

    # Method 1: Lock files (most reliable for TUI)
    if os.path.exists(sessions_dir):
        lock_files = glob.glob(os.path.join(sessions_dir, "*.lock"))
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
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    active_map = get_active_sessions()
    
    conn = sqlite3.connect(db_path)
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
            
            # Extract last user message for better differentiation
            preview = ""
            last_user_msg = ""
            for line in reversed(transcript):
                if not line.strip():
                    continue
                stripped = line.strip()
                if stripped.startswith("> "):
                    if not last_user_msg:
                        last_user_msg = stripped[2:].strip().replace("\n", " ")[:120]
                elif not preview:
                    preview = stripped.replace("\n", " ")[:100]
            
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
                f"{last_user_msg if last_user_msg else preview}\t"
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
                "data": data,
                "last_user_msg": last_user_msg
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
        "--info", "inline",
        "--footer", f"{DIM}ctrl-x: delete  tab: select multi{RESET}",
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
    db_path = get_db_path()
    sessions_dir = get_sessions_dir()
    conn = sqlite3.connect(db_path)
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
                path = os.path.join(sessions_dir, conv_id + ext)
                try:
                    os.remove(path)
                except OSError:
                    pass

    conn.commit()
    conn.close()


def update_session(session):
    if session["source"] == "v1":
        return

    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
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
    
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
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
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        return

    conn = sqlite3.connect(db_path)
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

def show_report():
    sessions = get_sessions()
    if not sessions:
        print("No sessions found.")
        return

    from datetime import date
    today = date.today()

    today_sessions = []
    for s in sessions:
        updated_at = s.get("updated_at", 0)
        if updated_at > 0:
            dt = datetime.fromtimestamp(updated_at / 1000)
            if dt.date() == today:
                today_sessions.append(s)

    if not today_sessions:
        print(f"No activity recorded for today ({today.strftime('%Y-%m-%d')}).")
        return

    print(f"{BOLD}{GREEN}--- Daily Accomplishments Report ({today.strftime('%Y-%m-%d')}) ---{RESET}")

    # Group by project
    projects = {}
    for s in today_sessions:
        project = os.path.basename(s["key"])
        if project not in projects:
            projects[project] = []
        projects[project].append(s)

    for project, p_sessions in projects.items():
        print(f"\n{BOLD}{BLUE}Project: {project}{RESET}")
        # Sort by updated_at ASC to show progress through the day
        for s in sorted(p_sessions, key=lambda x: x["updated_at"]):
            dt = datetime.fromtimestamp(s["updated_at"] / 1000)
            time_str = dt.strftime("%H:%M")

            summary = s["data"].get("latest_summary")
            content = summary if summary else s.get("last_user_msg", "Active session")

            print(f"  {DIM}[{time_str}]{RESET} {content}")
    print()

def show_timeline():
    sessions = get_sessions()
    if not sessions:
        print("No sessions found.")
        return

    from datetime import date, timedelta
    today = date.today()
    yesterday = today - timedelta(days=1)

    groups = {
        "TODAY": [],
        "YESTERDAY": [],
        "OLDER": {},
        "LEGACY / UNKNOWN": []
    }

    for s in sessions:
        updated_at = s.get("updated_at", 0)
        if updated_at == 0:
            groups["LEGACY / UNKNOWN"].append(s)
            continue

        dt = datetime.fromtimestamp(updated_at / 1000)
        session_date = dt.date()

        if session_date == today:
            groups["TODAY"].append(s)
        elif session_date == yesterday:
            groups["YESTERDAY"].append(s)
        else:
            date_str = session_date.strftime("%Y-%m-%d")
            if date_str not in groups["OLDER"]:
                groups["OLDER"][date_str] = []
            groups["OLDER"][date_str].append(s)

    def print_group(name, group_sessions):
        if not group_sessions:
            return
        print(f"\n{BOLD}{YELLOW}--- {name} ---{RESET}")
        for s in group_sessions:
            # Re-parse display to remove some fields for timeline view or just use parts
            parts = strip_ansi(s["display"]).split('\t')
            # 1:icon, 2:proj, 3:date, 4:model, 5:msgs, 6:preview
            status = parts[0]
            project = parts[1]
            time_str = parts[2].split(' ')[1] if ' ' in parts[2] else parts[2]
            model = parts[3]
            msgs = parts[4]
            preview = parts[5]

            # Use summary if available
            summary = s["data"].get("latest_summary")
            if summary:
                preview = f"{ITALIC}{summary[:100]}{RESET}"

            print(f"  {status} {BOLD}{BLUE}{project:15}{RESET} {DIM}{time_str}{RESET} {CYAN}{model:12}{RESET} {MAGENTA}{msgs:3}{RESET} {preview}")

    print_group("TODAY", groups["TODAY"])
    print_group("YESTERDAY", groups["YESTERDAY"])

    for date_str in sorted(groups["OLDER"].keys(), reverse=True):
        print_group(date_str, groups["OLDER"][date_str])

    print_group("LEGACY / UNKNOWN", groups["LEGACY / UNKNOWN"])
    print()

def show_stats():
    sessions = get_sessions()
    if not sessions:
        print("No sessions found.")
        return

    total = len(sessions)
    models = {}
    projects = {}
    total_msgs = 0

    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    query = "SELECT value FROM conversations_v2 UNION ALL SELECT value FROM conversations"
    cursor.execute(query)
    for row in cursor.fetchall():
        try:
            data = json.loads(row[0])
            model = data.get("model_info", {}).get("model_id", "unknown")
            models[model] = models.get(model, 0) + 1

            key = "unknown"
            # We don't have the key directly here easily without more complex query but we can infer from sessions
        except: continue
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
    for p, count in sorted(projects.items(), key=lambda x: x[1], reverse=True)[:5]:
        print(f"  {p:20} {count} sessions")

    print(f"\n{BOLD}Model Usage:{RESET}")
    for m, count in sorted(models.items(), key=lambda x: x[1], reverse=True):
        print(f"  {m:20} {count} sessions")

def search_sessions(query):
    all_sessions = get_sessions()
    results = []

    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
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
    parser_backup = subparsers.add_parser("backup", help="Dump sessions to markdown files")
    parser_backup.add_argument("dest_dir", help="Directory to dump session markdown files into")
    parser_backup.add_argument("--session-id", help="Optional specific session ID to dump")

    parser_stats = subparsers.add_parser("stats", help="Show session statistics")

    parser_timeline = subparsers.add_parser("timeline", help="Show chronological session history")

    parser_report = subparsers.add_parser("report", help="Generate a daily accomplishments report")

    parser_continue = subparsers.add_parser("continue", help="Resume the most recent session")
    parser_continue.add_argument("--project", help="Filter by project name (substring match)")

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

    if args.command == "timeline":
        show_timeline()
        return

    if args.command == "report":
        show_report()
        return

    if args.command == "continue":
        sessions = get_sessions()
        if not sessions:
            print("No sessions found.", file=sys.stderr)
            return

        selected = None
        if args.project:
            query = args.project.lower()
            for s in sessions:
                project = os.path.basename(s["key"]).lower()
                if query in project:
                    selected = s
                    break
            if not selected:
                print(f"No sessions found for project matching '{args.project}'", file=sys.stderr)
                return
        else:
            selected = sessions[0] # sessions are sorted by updated_at DESC

        if selected:
            update_session(selected)
            safe_key = shlex.quote(selected['key'])
            print(f"cd {safe_key} && kiro-cli chat --resume")
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
