import os
import sys
import json
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

# Configure environment variables before importing kiro_sessionizer
TEST_DB_PATH = os.path.abspath("test_data.sqlite3")
os.environ["KIRO_DB_PATH"] = TEST_DB_PATH

import kiro_sessionizer

@pytest.fixture(autouse=True)
def setup_test_db():
    # Setup fresh sqlite database for tests
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    conn = sqlite3.connect(TEST_DB_PATH)
    cursor = conn.cursor()

    # Create tables
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversations_v2 (
        key TEXT,
        conversation_id TEXT,
        value TEXT,
        created_at INTEGER,
        updated_at INTEGER,
        PRIMARY KEY (key, conversation_id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")

    # Insert mock data
    now_ms = int(datetime.now().timestamp() * 1000)

    # 1. Active mock session in conversations_v2
    v2_session_value = {
        "conversation_id": "v2-active-id",
        "history": [{"user": {"content": {"Prompt": {"prompt": "What is life?"}}}}],
        "transcript": ["> What is life?", "Assistant: Life is coding."],
        "model_info": {"model_id": "claude-3-opus"},
        "latest_summary": "Discussed the meaning of life.",
        "file_line_tracker": {
            "src/main.py": {"lines": [1, 2, 3]}
        }
    }
    cursor.execute(
        "INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
        ("/path/to/project_active", "v2-active-id", json.dumps(v2_session_value), now_ms, now_ms)
    )

    # 2. Legacy mock session in conversations
    v1_session_value = {
        "conversation_id": "legacy",
        "history": [{"user": {"content": {"Prompt": {"prompt": "Hello legacy!"}}}}],
        "transcript": ["> Hello legacy!", "Assistant: Hello user!"],
        "model_info": {"model_id": "gpt-4"},
        "latest_summary": "Legacy session work.",
        "file_line_tracker": {
            "legacy_file.txt": {"lines": [10]}
        }
    }
    cursor.execute(
        "INSERT INTO conversations VALUES (?, ?)",
        ("/path/to/project_legacy", json.dumps(v1_session_value))
    )

    conn.commit()
    conn.close()

    yield

    # Teardown
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


def test_get_sessions():
    sessions = kiro_sessionizer.get_sessions()
    assert len(sessions) == 2

    # Verify sorting and values
    v2_session = [s for s in sessions if s["source"] == "v2"][0]
    assert v2_session["key"] == "/path/to/project_active"
    assert v2_session["id"] == "v2-active-id"

    v1_session = [s for s in sessions if s["source"] == "v1"][0]
    assert v1_session["key"] == "/path/to/project_legacy"
    assert v1_session["id"] == "legacy"


def test_get_session_files():
    # v2 active files
    files = kiro_sessionizer.get_session_files("/path/to/project_active", "v2-active-id")
    # File existence is checked, so since src/main.py does not exist on test machine, returns []
    assert files == []

    # Let's mock os.path.exists and os.path.isfile to return True for files
    with patch("os.path.exists", return_value=True), patch("os.path.isfile", return_value=True):
        files = kiro_sessionizer.get_session_files("/path/to/project_active", "v2-active-id")
        assert len(files) == 1
        assert files[0].endswith("src/main.py")


def test_draft_git_commit(capsys):
    with patch("kiro_sessionizer.get_sessions") as mock_get_sessions:
        mock_get_sessions.return_value = [
            {
                "key": "/path/to/project_active",
                "id": "v2-active-id",
                "display": "",
                "source": "v2",
                "pid": None
            }
        ]
        kiro_sessionizer.draft_git_commit()
        captured = capsys.readouterr()
        assert "feat(project_active): work on session v2-activ" in captured.out
        assert "Discussed the meaning of life." in captured.out


def test_generate_journal(capsys):
    # Test project path matches setup_test_db inserts
    kiro_sessionizer.generate_journal("/path/to/project_active")
    captured = capsys.readouterr()
    assert "# Project Journal: project_active" in captured.out
    assert "Discussed the meaning of life." in captured.out


def test_generate_report(capsys):
    kiro_sessionizer.generate_report(days=7)
    captured = capsys.readouterr()
    assert "# Kiro Standup Report (Last 7 days)" in captured.out
    assert "project_active" in captured.out


def test_show_stats(capsys):
    kiro_sessionizer.show_stats()
    captured = capsys.readouterr()
    assert "Kiro Sessionizer Statistics" in captured.out
    assert "Total Sessions:" in captured.out
    assert "project_active" in captured.out


def test_prune_sessions_dry_run(capsys):
    # Dry run should only output information and not delete anything
    kiro_sessionizer.prune_sessions(days=30, min_messages=10, apply=False)
    captured = capsys.readouterr()
    assert "DRY RUN MODE" in captured.out

    # Check database still has 2 records
    conn = sqlite3.connect(TEST_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM conversations_v2")
    v2_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM conversations")
    v1_count = cursor.fetchone()[0]
    conn.close()
    assert v2_count == 1
    assert v1_count == 1
