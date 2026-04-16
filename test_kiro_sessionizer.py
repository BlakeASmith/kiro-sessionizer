import pytest
import os
import sqlite3
import json
import kiro_sessionizer
from datetime import datetime, timedelta

@pytest.fixture
def mock_db(tmp_path):
    db_path = tmp_path / "test_data.sqlite3"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE conversations_v2 (
            key TEXT,
            conversation_id TEXT,
            value TEXT,
            created_at INTEGER,
            updated_at INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE conversations (
            key TEXT,
            value TEXT
        )
    """)

    # Add some test data
    now_ms = int(datetime.now().timestamp() * 1000)
    yesterday_ms = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)

    # Session 1: Today, project A
    data1 = {
        "transcript": ["> User: Hello project A", "Assistant: Hi!"],
        "history": [{"role": "user", "content": "Hello project A"}],
        "latest_summary": "Discussed project A"
    }
    cursor.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
                   ("/path/to/projectA", "conv1", json.dumps(data1), now_ms, now_ms))

    # Session 2: Yesterday, project B
    data2 = {
        "transcript": ["> User: Yesterday work", "Assistant: Ok"],
        "history": [{"role": "user", "content": "Yesterday work"}]
    }
    cursor.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
                   ("/path/to/projectB", "conv2", json.dumps(data2), yesterday_ms, yesterday_ms))

    conn.commit()
    conn.close()

    # Monkeypatch the DB_PATH
    original_db_path = kiro_sessionizer.DB_PATH
    kiro_sessionizer.DB_PATH = str(db_path)
    yield db_path
    kiro_sessionizer.DB_PATH = original_db_path

def test_get_sessions(mock_db):
    sessions = kiro_sessionizer.get_sessions()
    assert len(sessions) == 2
    assert sessions[0]["id"] == "conv1"
    assert "data" in sessions[0]
    assert sessions[0]["data"]["latest_summary"] == "Discussed project A"

def test_continue_with_project(mock_db, capsys):
    # Mocking select_session is not needed for 'continue'
    kiro_sessionizer.main_with_args(["continue", "--project", "projectA"])
    captured = capsys.readouterr()
    assert "cd /path/to/projectA && kiro-cli chat --resume" in captured.out

def test_continue_no_project(mock_db, capsys):
    kiro_sessionizer.main_with_args(["continue"])
    captured = capsys.readouterr()
    assert "cd /path/to/projectA && kiro-cli chat --resume" in captured.out

def test_timeline(mock_db, capsys):
    kiro_sessionizer.main_with_args(["timeline"])
    captured = capsys.readouterr()
    assert "--- TODAY ---" in captured.out
    assert "projectA" in captured.out
    assert "--- YESTERDAY ---" in captured.out
    assert "projectB" in captured.out

def test_report(mock_db, capsys):
    kiro_sessionizer.main_with_args(["report"])
    captured = capsys.readouterr()
    assert "Daily Accomplishments Report" in captured.out
    assert "Project: projectA" in captured.out
    assert "Discussed project A" in captured.out
    assert "projectB" not in captured.out

# Helper to run main with specific args
def main_with_args(args):
    import sys
    import argparse
    original_argv = sys.argv
    sys.argv = ["kiro_sessionizer.py"] + args
    try:
        kiro_sessionizer.main()
    finally:
        sys.argv = original_argv

kiro_sessionizer.main_with_args = main_with_args
