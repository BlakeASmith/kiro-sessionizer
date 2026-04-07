import sqlite3
import json
import os
import time
from datetime import datetime, timedelta

DB_PATH = "data.sqlite3"

def create_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE conversations_v2 (
        key TEXT,
        conversation_id TEXT,
        value TEXT,
        updated_at INTEGER
    )
    """)

    cursor.execute("""
    CREATE TABLE conversations (
        key TEXT,
        value TEXT
    )
    """)

    now_ms = int(time.time() * 1000)
    yesterday_ms = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)
    three_days_ago_ms = int((datetime.now() - timedelta(days=3)).timestamp() * 1000)
    ten_days_ago_ms = int((datetime.now() - timedelta(days=10)).timestamp() * 1000)

    sessions = [
        # Today
        ("/path/to/project-a", "conv-1", {
            "model_info": {"model_id": "gpt-4"},
            "history": [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}],
            "transcript": ["> Hello", "Assistant: Hi"],
            "latest_summary": "Discussed project architecture."
        }, now_ms),

        # Today - another one
        ("/path/to/project-b", "conv-2", {
            "model_info": {"model_id": "gpt-3.5-turbo"},
            "history": [{"role": "user", "content": "Fix bug"}, {"role": "assistant", "content": "Done"}],
            "transcript": ["> Fix bug", "Assistant: Done"],
            "latest_summary": "Fixed a memory leak in the worker."
        }, now_ms - 1000),

        # Yesterday
        ("/path/to/project-a", "conv-3", {
            "model_info": {"model_id": "gpt-4"},
            "history": [{"role": "user", "content": "Test setup"}],
            "transcript": ["> Test setup"],
            "latest_summary": "Set up pytest environment."
        }, yesterday_ms),

        # 3 days ago
        ("/path/to/project-c", "conv-4", {
            "model_info": {"model_id": "claude-3"},
            "history": [{"role": "user", "content": "Refactor"}],
            "transcript": ["> Refactor"],
            "latest_summary": "Refactored the database module."
        }, three_days_ago_ms),

        # 10 days ago
        ("/path/to/project-b", "conv-5", {
            "model_info": {"model_id": "gpt-4"},
            "history": [{"role": "user", "content": "Initial commit"}],
            "transcript": ["> Initial commit"],
            "latest_summary": "Project initialization."
        }, ten_days_ago_ms),
    ]

    for key, conv_id, val_dict, updated_at in sessions:
        cursor.execute(
            "INSERT INTO conversations_v2 (key, conversation_id, value, updated_at) VALUES (?, ?, ?, ?)",
            (key, conv_id, json.dumps(val_dict), updated_at)
        )

    # Legacy session
    cursor.execute(
        "INSERT INTO conversations (key, value) VALUES (?, ?)",
        ("/path/to/legacy-proj", json.dumps({
            "transcript": ["> Legacy query"],
            "history": [{"role": "user", "content": "Legacy query"}]
        }))
    )

    conn.commit()
    conn.close()
    print(f"Mock database created at {DB_PATH}")

if __name__ == "__main__":
    create_db()
