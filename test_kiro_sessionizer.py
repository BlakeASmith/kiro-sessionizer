import os
import sys
import tempfile
import sqlite3
import json
from datetime import datetime

# Set the environment variable BEFORE importing kiro_sessionizer
temp_db_fd, temp_db_path = tempfile.mkstemp()
os.environ["KIRO_DB_PATH"] = temp_db_path

import kiro_sessionizer

def setup_module(module):
    # Populate mock database
    conn = sqlite3.connect(temp_db_path)
    cursor = conn.cursor()

    # Create conversations_v2
    cursor.execute("""
    CREATE TABLE conversations_v2 (
        key TEXT,
        conversation_id TEXT,
        value TEXT,
        created_at INTEGER,
        updated_at INTEGER,
        PRIMARY KEY (key, conversation_id)
    )
    """)

    # Create legacy conversations
    cursor.execute("""
    CREATE TABLE conversations (
        key TEXT,
        value TEXT
    )
    """)

    # Mock conversation data
    v2_value = {
        "conversation_id": "test-v2-uuid",
        "history": [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}],
        "transcript": ["> hello", "Assistant: hi"],
        "latest_summary": "Discussed greeting.",
        "model_info": {"model_id": "gpt-4"},
        "file_line_tracker": {
            "/path/to/project/main.py": {"lines": [1, 2]},
            "/path/to/project/utils.py": {"lines": [5]}
        }
    }

    v1_value = {
        "history": [{"role": "user", "content": "legacy help"}],
        "transcript": ["> legacy help", "Assistant: sure"],
        "latest_summary": "Legacy session support.",
        "model_info": {"model_id": "gpt-3.5-turbo"},
        "file_line_tracker": {
            "/path/to/project/legacy_helper.py": {"lines": [10]}
        }
    }

    # Insert rows
    cursor.execute(
        "INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
        ("/path/to/project", "test-v2-uuid", json.dumps(v2_value), int(datetime.now().timestamp() * 1000), int(datetime.now().timestamp() * 1000))
    )

    cursor.execute(
        "INSERT INTO conversations VALUES (?, ?)",
        ("/path/to/project/legacy", json.dumps(v1_value))
    )

    conn.commit()
    conn.close()

def teardown_module(module):
    os.close(temp_db_fd)
    if os.path.exists(temp_db_path):
        os.remove(temp_db_path)

def test_show_stats(capsys):
    kiro_sessionizer.show_stats()
    captured = capsys.readouterr()
    assert "Total Sessions" in captured.out
    assert "Top Projects" in captured.out
    assert "Top Files Discussed" in captured.out
    assert "main.py" in captured.out
    assert "utils.py" in captured.out
    assert "legacy_helper.py" in captured.out

def test_prune_sessions_dry_run(capsys):
    kiro_sessionizer.prune_sessions(days=10, min_messages=None, apply=False, force=False)
    captured = capsys.readouterr()
    assert "Found 1 sessions matching criteria" in captured.out
    assert "DRY RUN MODE" in captured.out

def test_journal_project(capsys):
    kiro_sessionizer.journal_project("/path/to/project")
    captured = capsys.readouterr()
    assert "Project Journal: project" in captured.out
    assert "Discussed greeting" in captured.out

def test_generate_report(capsys):
    kiro_sessionizer.generate_report(days=2, project_filter="project")
    captured = capsys.readouterr()
    assert "Kiro Developer Standup Report" in captured.out
    assert "project" in captured.out
    assert "Discussed greeting" in captured.out

def test_draft_commit(capsys):
    kiro_sessionizer.draft_commit()
    captured = capsys.readouterr()
    assert "ai(project): update project workspace" in captured.out
    assert "Discussed greeting" in captured.out
