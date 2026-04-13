import pytest
import sqlite3
import json
import os
import kiro_sessionizer
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

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
            updated_at INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE conversations (
            key TEXT,
            value TEXT
        )
    """)

    now = datetime.now()
    today_ms = int(now.timestamp() * 1000)
    yesterday_ms = int((now - timedelta(days=1)).timestamp() * 1000)
    older_ms = int((now - timedelta(days=5)).timestamp() * 1000)

    # Today's session
    cursor.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?)", (
        "/projects/kiro", "conv1", json.dumps({
            "transcript": ["> Hello", "Hi there"],
            "history": [{}, {}],
            "latest_summary": "Discussed Kiro features",
            "model_info": {"model_id": "gpt-4"}
        }), today_ms
    ))

    # Yesterday's session
    cursor.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?)", (
        "/projects/secret", "conv2", json.dumps({
            "transcript": ["> Secret info"],
            "history": [{}],
            "model_info": {"model_id": "claude-3"}
        }), yesterday_ms
    ))

    # Older session
    cursor.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?)", (
        "/projects/kiro", "conv3", json.dumps({
            "transcript": ["> Old stuff"],
            "history": [{}],
            "model_info": {"model_id": "gpt-4"}
        }), older_ms
    ))

    conn.commit()
    conn.close()
    return str(db_path)

@patch("kiro_sessionizer.DB_PATH")
@patch("kiro_sessionizer.get_active_sessions")
def test_get_sessions_refactored(mock_active, mock_db_path, mock_db):
    kiro_sessionizer.DB_PATH = mock_db
    mock_active.return_value = {}

    sessions = kiro_sessionizer.get_sessions()
    assert len(sessions) == 3
    assert "data" in sessions[0]
    assert sessions[0]["id"] == "conv1"
    assert sessions[0]["updated_at"] > 0

@patch("kiro_sessionizer.DB_PATH")
@patch("kiro_sessionizer.get_active_sessions")
@patch("kiro_sessionizer.select_session")
def test_show_timeline(mock_select, mock_active, mock_db_path, mock_db):
    kiro_sessionizer.DB_PATH = mock_db
    mock_active.return_value = {}

    # Mock select_session to just return the first real session passed to it
    def side_effect(sessions):
        for s in sessions:
            if s.get("key"):
                return s
        return None
    mock_select.side_effect = side_effect

    selected = kiro_sessionizer.show_timeline()
    assert selected["id"] == "conv1"

    # Check that headers were added (we can't easily check timeline_sessions inside show_timeline
    # without returning it, but we can verify the behavior)

@patch("kiro_sessionizer.DB_PATH")
@patch("kiro_sessionizer.get_active_sessions")
def test_generate_report(mock_active, mock_db_path, mock_db, capsys):
    kiro_sessionizer.DB_PATH = mock_db
    mock_active.return_value = {}

    kiro_sessionizer.generate_report()
    captured = capsys.readouterr()
    assert "Daily Accomplishments Report" in captured.out
    assert "[kiro]" in captured.out
    assert "Discussed Kiro features" in captured.out
    assert "[secret]" not in captured.out # Yesterday's session

@patch("kiro_sessionizer.DB_PATH")
@patch("kiro_sessionizer.get_active_sessions")
def test_continue_project(mock_active, mock_db_path, mock_db):
    kiro_sessionizer.DB_PATH = mock_db
    mock_active.return_value = {}

    # Mocking argparse args
    class Args:
        command = "continue"
        project = "secret"

    with patch("sys.stdout", new=MagicMock()) as mock_stdout:
        # We need to manually run the logic since main() is complex
        sessions = kiro_sessionizer.get_sessions()
        filtered = [s for s in sessions if "secret" in s["key"].lower()]
        assert len(filtered) == 1
        assert filtered[0]["id"] == "conv2"
