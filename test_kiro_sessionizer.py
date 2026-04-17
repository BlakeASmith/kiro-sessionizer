import pytest
import sqlite3
import json
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import kiro_sessionizer

@pytest.fixture
def mock_db_file(tmp_path):
    db_path = tmp_path / "data.sqlite3"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversations_v2 (
        key TEXT,
        conversation_id TEXT,
        value TEXT,
        created_at INTEGER,
        updated_at INTEGER
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        key TEXT,
        value TEXT
    )
    """)

    now_ms = int(datetime.now().timestamp() * 1000)
    yesterday_ms = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)

    # Session 1: Today, project A, with summary
    data1 = {
        "transcript": ["> Hello", "Hi there"],
        "history": [{}, {}],
        "model_info": {"model_id": "gpt-4"},
        "latest_summary": "Discussed project A architecture."
    }
    cursor.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
                   ("/home/user/projectA", "uuid1", json.dumps(data1), now_ms, now_ms))

    # Session 2: Today, project B, no summary
    data2 = {
        "transcript": ["> Fix bug in auth", "Sure"],
        "history": [{}, {}],
        "model_info": {"model_id": "gpt-3.5"}
    }
    cursor.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
                   ("/home/user/projectB", "uuid2", json.dumps(data2), now_ms, now_ms))

    # Session 3: Yesterday, project A
    data3 = {
        "transcript": ["> Setup CI", "Done"],
        "history": [{}, {}]
    }
    cursor.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
                   ("/home/user/projectA", "uuid3", json.dumps(data3), yesterday_ms, yesterday_ms))

    conn.commit()
    conn.close()
    return str(db_path)

def test_get_sessions_metadata(mock_db_file):
    with patch("kiro_sessionizer.DB_PATH", mock_db_file):
        with patch("kiro_sessionizer.get_active_sessions", return_value={}):
            with patch("os.path.exists", return_value=True):
                sessions = kiro_sessionizer.get_sessions()
                assert len(sessions) == 3
                assert "updated_at" in sessions[0]
                assert "data" in sessions[0]
                assert "last_user_msg" in sessions[0]
                assert sessions[0]["last_user_msg"] == "Hello"

@patch("kiro_sessionizer.get_sessions")
def test_timeline_grouping(mock_get_sessions):
    now_ms = int(datetime.now().timestamp() * 1000)
    yesterday_ms = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)

    mock_get_sessions.return_value = [
        {"key": "/projA", "updated_at": now_ms, "data": {}, "pid": None, "last_user_msg": "msg1"},
        {"key": "/projA", "updated_at": yesterday_ms, "data": {}, "pid": None, "last_user_msg": "msg2"},
        {"key": "/legacy", "updated_at": 0, "data": {}, "pid": None, "last_user_msg": "msg3"}
    ]

    with patch("sys.stdout.write") as mock_write:
        kiro_sessionizer.show_timeline()
        output = "".join(call.args[0] for call in mock_write.call_args_list)
        assert "--- TODAY ---" in output
        assert "--- YESTERDAY ---" in output
        assert "--- LEGACY / UNKNOWN ---" in output

@patch("kiro_sessionizer.get_sessions")
def test_report_generation(mock_get_sessions):
    now_ms = int(datetime.now().timestamp() * 1000)
    mock_get_sessions.return_value = [
        {
            "key": "/projA",
            "updated_at": now_ms,
            "data": {"latest_summary": "Did work on A"},
            "pid": None,
            "last_user_msg": "ignore me"
        },
        {
            "key": "/projB",
            "updated_at": now_ms,
            "data": {},
            "pid": None,
            "last_user_msg": "Started B"
        }
    ]

    with patch("sys.stdout.write") as mock_write:
        kiro_sessionizer.generate_report()
        output = "".join(call.args[0] for call in mock_write.call_args_list)
        assert "Project: projA" in output
        assert "Did work on A" in output
        assert "Project: projB" in output
        assert "Started B" in output

@patch("kiro_sessionizer.get_sessions")
@patch("kiro_sessionizer.update_session")
def test_continue_project_filter(mock_update, mock_get_sessions):
    mock_get_sessions.return_value = [
        {"key": "/home/user/apple", "updated_at": 100, "data": {}, "id": "1"},
        {"key": "/home/user/banana", "updated_at": 90, "data": {}, "id": "2"}
    ]

    # Mock sys.argv for 'continue --project banana'
    with patch.object(sys, 'argv', ['kiro_sessionizer.py', 'continue', '--project', 'banana']):
        with patch("sys.stdout.write") as mock_write:
            kiro_sessionizer.main()
            output = "".join(call.args[0] for call in mock_write.call_args_list)
            assert "cd /home/user/banana" in output
            assert "kiro-cli chat --resume" in output

    # Test no match
    with patch.object(sys, 'argv', ['kiro_sessionizer.py', 'continue', '--project', 'cherry']):
        with patch("sys.stderr.write") as mock_stderr:
            kiro_sessionizer.main()
            output = "".join(call.args[0] for call in mock_stderr.call_args_list)
            assert "No sessions found for project matching 'cherry'" in output
