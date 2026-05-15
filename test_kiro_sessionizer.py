import pytest
import kiro_sessionizer
from datetime import datetime, timedelta
import json
import sqlite3
import os
import tempfile
from unittest.mock import patch, MagicMock

def test_strip_ansi():
    assert kiro_sessionizer.strip_ansi("\033[34mHello\033[0m") == "Hello"
    assert kiro_sessionizer.strip_ansi("\033[1;31mWorld\033[0m") == "World"
    assert kiro_sessionizer.strip_ansi("Plain") == "Plain"

@patch('kiro_sessionizer.DB_PATH')
def test_generate_report_no_activity(mock_db_path, capsys):
    with tempfile.NamedTemporaryFile() as tmp:
        mock_db_path.return_value = tmp.name
        conn = sqlite3.connect(tmp.name)
        conn.execute("CREATE TABLE conversations_v2 (key TEXT, value TEXT, updated_at INTEGER)")
        conn.close()

        with patch('kiro_sessionizer.DB_PATH', tmp.name):
            kiro_sessionizer.generate_report()
            captured = capsys.readouterr()
            assert "No activity today." in captured.out

@patch('kiro_sessionizer.get_sessions')
def test_show_timeline_basic(mock_get_sessions, capsys):
    today = int(datetime.now().timestamp() * 1000)
    yesterday = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)

    mock_get_sessions.return_value = [
        {"display": "today_session", "updated_at": today},
        {"display": "yesterday_session", "updated_at": yesterday},
        {"display": "legacy_session", "updated_at": 0}
    ]

    kiro_sessionizer.show_timeline()
    captured = capsys.readouterr()
    assert "--- TODAY ---" in captured.out
    assert "today_session" in captured.out
    assert "--- YESTERDAY ---" in captured.out
    assert "yesterday_session" in captured.out
    assert "--- LEGACY / UNKNOWN ---" in captured.out
    assert "legacy_session" in captured.out

def test_generate_report_with_activity(capsys):
    with tempfile.NamedTemporaryFile() as tmp:
        db_path = tmp.name
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE conversations_v2 (key TEXT, conversation_id TEXT, value TEXT, created_at INTEGER, updated_at INTEGER)")

        now_ms = int(datetime.now().timestamp() * 1000)
        value = json.dumps({
            "latest_summary": "Test Summary",
            "transcript": ["> User: Hi", "Assistant: Hello"]
        })
        conn.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)", ("/path/to/project", "id1", value, now_ms, now_ms))
        conn.commit()
        conn.close()

        with patch('kiro_sessionizer.DB_PATH', db_path):
            kiro_sessionizer.generate_report()
            captured = capsys.readouterr()
            assert "Daily Accomplishments Report" in captured.out
            assert "Project: project" in captured.out
            assert "- Test Summary" in captured.out

def test_generate_report_fallback_summary(capsys):
    with tempfile.NamedTemporaryFile() as tmp:
        db_path = tmp.name
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE conversations_v2 (key TEXT, conversation_id TEXT, value TEXT, created_at INTEGER, updated_at INTEGER)")

        now_ms = int(datetime.now().timestamp() * 1000)
        value = json.dumps({
            "latest_summary": None,
            "transcript": ["> User: My fallback message", "Assistant: Hello"]
        })
        conn.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)", ("/path/to/project", "id1", value, now_ms, now_ms))
        conn.commit()
        conn.close()

        with patch('kiro_sessionizer.DB_PATH', db_path):
            kiro_sessionizer.generate_report()
            captured = capsys.readouterr()
            assert "Project: project" in captured.out
            assert "- My fallback message" in captured.out
