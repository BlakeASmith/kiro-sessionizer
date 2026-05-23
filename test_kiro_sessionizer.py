import os
import sqlite3
import json
import time
import pytest
import importlib
import kiro_sessionizer

@pytest.fixture
def mock_db(tmp_path):
    db_path = tmp_path / "test_kiro.sqlite3"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("CREATE TABLE conversations (key TEXT, value TEXT)")
    c.execute("CREATE TABLE conversations_v2 (key TEXT, conversation_id TEXT, value TEXT, created_at INTEGER, updated_at INTEGER)")

    # Today's session
    now_ms = int(time.time() * 1000)
    data = json.dumps({"transcript": ["> hello", "hi"], "history": [{}, {}], "latest_summary": "Greeting"})
    c.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)", ("/projects/a", "uuid-a", data, now_ms, now_ms))

    # Yesterday's session
    yesterday_ms = now_ms - (24 * 60 * 60 * 1000)
    data_b = json.dumps({"transcript": ["> yesterday query"], "history": [{}]})
    c.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)", ("/projects/b", "uuid-b", data_b, yesterday_ms, yesterday_ms))

    # Legacy session
    c.execute("INSERT INTO conversations VALUES (?, ?)", ("/projects/c", json.dumps({"transcript": ["legacy"] })))

    conn.commit()
    conn.close()

    original_db_path = os.environ.get("KIRO_DB_PATH")
    os.environ["KIRO_DB_PATH"] = str(db_path)
    importlib.reload(kiro_sessionizer)

    yield db_path

    if original_db_path:
        os.environ["KIRO_DB_PATH"] = original_db_path
    else:
        del os.environ["KIRO_DB_PATH"]
    importlib.reload(kiro_sessionizer)

def test_get_sessions(mock_db):
    sessions = kiro_sessionizer.get_sessions()
    assert len(sessions) == 3
    assert sessions[0]["id"] == "uuid-a"
    assert sessions[1]["id"] == "uuid-b"
    assert sessions[2]["id"] == "legacy"

def test_fork_session(mock_db):
    sessions_before = kiro_sessionizer.get_sessions()
    assert len(sessions_before) == 3

    kiro_sessionizer.fork_session("uuid-a", "/projects/a")

    sessions_after = kiro_sessionizer.get_sessions()
    assert len(sessions_after) == 4
    # The newest should be the fork
    assert sessions_after[0]["key"] == "/projects/a"
    assert sessions_after[0]["id"] != "uuid-a"
    assert "[Session forked from uuid-a]" in sessions_after[0]["data"]["transcript"]

def test_report(mock_db, capsys):
    kiro_sessionizer.generate_report()
    captured = capsys.readouterr()
    assert "DAILY ACTIVITY REPORT" in captured.out
    assert "PROJECT: a" in captured.out
    assert "Greeting" in captured.out
    assert "PROJECT: b" not in captured.out

def test_timeline(mock_db, capsys):
    kiro_sessionizer.show_timeline()
    captured = capsys.readouterr()
    assert "--- TODAY ---" in captured.out
    assert "--- YESTERDAY ---" in captured.out
    assert "--- LEGACY ---" in captured.out
