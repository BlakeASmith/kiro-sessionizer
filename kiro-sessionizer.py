#!/usr/bin/env python3
import sqlite3
import json
import os
import sys
import subprocess
from datetime import datetime
import re

DB_PATH = os.path.expanduser("~/Library/Application Support/kiro-cli/data.sqlite3")

# ANSI Color Codes
BLUE = "\033[34m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
RESET = "\033[0m"

def strip_ansi(text):
    return re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])').sub('', text)

def get_sessions():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

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
            
            preview = ""
            for line in reversed(transcript):
                if line.strip():
                    preview = line.strip().replace("\n", " ")[:100]
                    break
            
            dt = datetime.fromtimestamp(updated_at / 1000) if updated_at > 0 else datetime.now()
            date_str = dt.strftime("%Y-%m-%d %H:%M")
            
            project = os.path.basename(key)
            
            # Using \t as a delimiter for fzf
            display = (
                f"{BOLD}{BLUE}{project: <20}{RESET}\t"
                f"{YELLOW}{date_str}{RESET}\t"
                f"{CYAN}{model: <15}{RESET}\t"
                f"{MAGENTA}{msg_count: >3} msgs{RESET}\t"
                f"{GREEN}{key}{RESET}\t"
                f"{preview}"
            )
            
            sessions.append({
                "key": key,
                "id": conv_id,
                "display": display,
                "source": source
            })
        except Exception:
            continue
            
    return sessions

def select_session(sessions):
    fzf_input = "\n".join([s["display"] for s in sessions])
    
    try:
        process = subprocess.Popen(
            [
                "fzf",
                "--ansi",
                "--delimiter", "\t",
                "--with-nth", "1,2,3,4,5,6",
                "--header", f"{BOLD}{BLUE}Project             {YELLOW}Date            {CYAN}Model          {MAGENTA}Msgs  {GREEN}Path{RESET}",
                "--reverse",
                "--height", "100%",
                "--preview-window", "bottom:60%:wrap",
                "--pointer", "▶",
                "--marker", "✓",
                "--color", "header:italic:underline,pointer:bold:blue,marker:bold:green",
                "--preview", f"python3 {__file__} --preview {{5}} {{1}}"
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True
        )
        stdout, _ = process.communicate(input=fzf_input)
        
        if process.returncode != 0 or not stdout:
            return None
            
        selected_display = stdout.strip()
        stripped_selected = strip_ansi(selected_display)
        
        for s in sessions:
            if strip_ansi(s["display"]) == stripped_selected:
                return s
    except FileNotFoundError:
        print("Error: 'fzf' is not installed.", file=sys.stderr)
        sys.exit(1)
        
    return None

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

def run_preview(path_ansi, project_ansi):
    path = strip_ansi(path_ansi).strip()
    project = strip_ansi(project_ansi).strip()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT value FROM conversations_v2 WHERE key = ? ORDER BY updated_at DESC LIMIT 1",
        (path,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        # Try v1 if v2 fails
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM conversations WHERE key = ?", (path,))
        row = cursor.fetchone()
        conn.close()
        
    if not row:
        print(f"No detailed data for {path}")
        return

    try:
        data = json.loads(row[0])
        model = data.get("model_info", {}).get("model_id", "auto")
        history = data.get("history", [])
        summary = data.get("latest_summary")
        transcript = data.get("transcript", [])
        
        try:
            cols = os.get_terminal_size().columns
        except:
            cols = 80
            
        # Meta info header
        print(f"{BOLD}{BLUE}PROJECT:{RESET} {project} {DIM}({path}){RESET}")
        print(f"{BOLD}{CYAN}MODEL:  {RESET} {model} | {BOLD}{MAGENTA}MESSAGES:{RESET} {len(history)}")
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
            
            # Detect User vs Assistant
            if line.startswith("> "):
                # User Prompt
                if current_speaker != "USER":
                    print(f"{BOLD}{CYAN}USER 👤{RESET}")
                    current_speaker = "USER"
                content = line[2:].strip()
                print(f"  {content}\n")
            elif line.startswith("[Tool uses:"):
                # Tool use metadata
                print(f"  {DIM}{ITALIC}{line}{RESET}")
                # Don't change speaker for tool metadata
            else:
                # Assistant Response
                if current_speaker != "KIRO":
                    print(f"{BOLD}{GREEN}KIRO 🤖{RESET}")
                    current_speaker = "KIRO"
                
                # Strip "Assistant: " prefix if it exists
                content = line
                if content.startswith("Assistant:"):
                    content = content[10:].strip()
                
                print(f"  {content}\n")
                    
    except Exception as e:
        import traceback
        print(f"Error parsing preview: {e}")
        traceback.print_exc()

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--preview":
        run_preview(sys.argv[2], sys.argv[3])
        return

    sessions = get_sessions()
    if not sessions:
        print("No sessions found.", file=sys.stderr)
        return

    selected = select_session(sessions)
    if selected:
        update_session(selected)
        print(f"cd '{selected['key']}' && kiro-cli chat --resume")

if __name__ == "__main__":
    main()
