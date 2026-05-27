import os
import json
import sqlite3
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import kiro_sessionizer
import importlib

@pytest.fixture
def mock_db(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE conversations_v2 (key TEXT, conversation_id TEXT, value TEXT, created_at INTEGER, updated_at INTEGER, PRIMARY KEY (key, conversation_id))")
    cursor.execute("CREATE TABLE conversations (key TEXT PRIMARY KEY, value TEXT)")

    # Add a session from today
    now_ms = int(datetime.now().timestamp() * 1000)
    val = json.dumps({
        "transcript": ["> User: Hello", "Assistant: Hi"],
        "history": [{}, {}],
        "model_info": {"model_id": "gpt-4"}
    })
    cursor.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)", ("/path/to/proj1", "id-1", val, now_ms, now_ms))

    # Add a session from yesterday
    yesterday_ms = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)
    cursor.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)", ("/path/to/proj2", "id-2", val, yesterday_ms, yesterday_ms))

    conn.commit()
    conn.close()

    with patch.dict(os.environ, {"KIRO_DB_PATH": str(db_path)}):
        importlib.reload(kiro_sessionizer)
        yield db_path

def test_get_sessions(mock_db):
    sessions = kiro_sessionizer.get_sessions()
    assert len(sessions) == 2
    assert sessions[0]["id"] == "id-1"
    assert sessions[0]["data"]["model_info"]["model_id"] == "gpt-4"
    assert "Hello" in sessions[0]["display"]

def test_fork_session(mock_db):
    kiro_sessionizer.fork_session("id-1", "/path/to/proj1")
    sessions = kiro_sessionizer.get_sessions()
    assert len(sessions) == 3

    forked = next(s for s in sessions if s["id"] not in ("id-1", "id-2"))
    assert "[Session forked from id-1]" in forked["data"]["transcript"]

def test_show_timeline_output(mock_db, capsys):
    kiro_sessionizer.show_timeline()
    captured = capsys.readouterr().out
    assert "TODAY" in captured
    assert "YESTERDAY" in captured
    assert "proj1" in captured
    assert "proj2" in captured

def test_generate_report(mock_db, capsys):
    kiro_sessionizer.generate_report()
    captured = capsys.readouterr().out
    assert "Daily Activity Report" in captured
    assert "proj1" in captured
    assert "Hello" in captured
