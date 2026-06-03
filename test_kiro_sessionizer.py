import pytest
import os
import sqlite3
import json
import subprocess
from unittest.mock import patch, MagicMock
from kiro_sessionizer import get_sessions, get_active_sessions, delete_sessions, prune_sessions

@pytest.fixture
def mock_db(tmp_path):
    db_path = tmp_path / "data.sqlite3"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE conversations_v2 (key TEXT, conversation_id TEXT, value TEXT, created_at INTEGER, updated_at INTEGER)")
    cursor.execute("CREATE TABLE conversations (key TEXT, value TEXT)")

    # Add a v2 session
    v2_value = json.dumps({
        "history": [{}, {}],
        "transcript": ["> Hello", "Assistant: Hi"],
        "model_info": {"model_id": "gpt-4"}
    })
    cursor.execute("INSERT INTO conversations_v2 VALUES ('/tmp/proj1', 'uuid1', ?, 1700000000000, 1700000000000)", (v2_value,))

    # Add a legacy session
    v1_value = json.dumps({
        "history": [{}],
        "transcript": ["> Legacy"],
        "model_info": {"model_id": "gpt-3.5"}
    })
    cursor.execute("INSERT INTO conversations VALUES ('/tmp/legacy', ?)", (v1_value,))

    conn.commit()
    conn.close()
    return str(db_path)

def test_get_sessions(mock_db):
    with patch("kiro_sessionizer.DB_PATH", mock_db):
        with patch("kiro_sessionizer.get_active_sessions", return_value={}):
            sessions = get_sessions()
            assert len(sessions) == 2
            assert sessions[0]["key"] == "/tmp/proj1"
            assert sessions[1]["key"] == "/tmp/legacy"

def test_get_active_sessions_lock_file(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    lock_file = sessions_dir / "uuid1.lock"
    json_file = sessions_dir / "uuid1.json"

    lock_file.write_text(json.dumps({"pid": 12345}))
    json_file.write_text(json.dumps({"cwd": "/tmp/proj1"}))

    with patch("kiro_sessionizer.SESSIONS_DIR", str(sessions_dir)):
        with patch("kiro_sessionizer.is_process_running", return_value=True):
            active = get_active_sessions()
            assert active["/tmp/proj1"] == 12345

def test_delete_sessions(mock_db, tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "uuid1.json").write_text("{}")

    with patch("kiro_sessionizer.DB_PATH", mock_db):
        with patch("kiro_sessionizer.SESSIONS_DIR", str(sessions_dir)):
            delete_sessions([("uuid1", "/tmp/proj1")])

            conn = sqlite3.connect(mock_db)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM conversations_v2 WHERE conversation_id='uuid1'")
            assert cursor.fetchone() is None
            conn.close()

            assert not (sessions_dir / "uuid1.json").exists()

def test_prune_sessions_dry_run(mock_db, capsys):
    with patch("kiro_sessionizer.DB_PATH", mock_db):
        prune_sessions(days=365, min_messages=0, dry_run=True)
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out
        assert "/tmp/proj1" in captured.out
