import pytest
import os
import json
import sqlite3
import subprocess
from kiro_sessionizer import strip_ansi

@pytest.fixture
def mock_db(tmp_path):
    db_path = tmp_path / "data.sqlite3"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE conversations_v2 (key TEXT, conversation_id TEXT, value TEXT, created_at INTEGER, updated_at INTEGER)")
    cursor.execute("CREATE TABLE conversations (key TEXT, value TEXT)")

    val = {
        "conversation_id": "test-id",
        "transcript": ["> User: Hello", "Assistant: Hi"],
        "history": [{}, {}],
        "model_info": {"model_id": "test-model"},
        "latest_summary": "Test Summary"
    }

    cursor.execute(
        "INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
        ("/tmp/project", "test-id", json.dumps(val), 1000, 2000)
    )
    conn.commit()
    conn.close()
    return str(db_path)

def test_strip_ansi():
    text = "\033[34mHello\033[0m"
    assert strip_ansi(text) == "Hello"

def test_get_sessions(mock_db, monkeypatch):
    monkeypatch.setattr("kiro_sessionizer.DB_PATH", mock_db)
    monkeypatch.setattr("kiro_sessionizer.get_active_sessions", lambda: {})

    from kiro_sessionizer import get_sessions
    sessions = get_sessions()

    assert len(sessions) == 1
    assert sessions[0]["id"] == "test-id"
    assert "Test Summary" in sessions[0]["display"]

def test_fork_session(mock_db, monkeypatch):
    monkeypatch.setattr("kiro_sessionizer.DB_PATH", mock_db)
    from kiro_sessionizer import fork_session

    new_id = fork_session("test-id", "/tmp/project")
    assert new_id is not None
    assert new_id != "test-id"

    conn = sqlite3.connect(mock_db)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM conversations_v2")
    count = cursor.fetchone()[0]
    assert count == 2
    conn.close()
