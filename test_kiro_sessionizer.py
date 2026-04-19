import pytest
from unittest.mock import patch, MagicMock
import json
import os
from datetime import datetime, timedelta
import kiro_sessionizer

def test_strip_ansi():
    text = "\033[34mProject\033[0m"
    assert kiro_sessionizer.strip_ansi(text) == "Project"

    text = "Plain text"
    assert kiro_sessionizer.strip_ansi(text) == "Plain text"

    # Test complex ANSI
    text = "\x1B[1;32mBold Green\x1B[0m"
    assert kiro_sessionizer.strip_ansi(text) == "Bold Green"

@patch('sqlite3.connect')
@patch('os.path.exists')
def test_get_sessions(mock_exists, mock_connect):
    mock_exists.return_value = True

    # Mock SQLite
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    # Mock active sessions
    with patch('kiro_sessionizer.get_active_sessions', return_value={}):
        # Mock rows
        # key, conversation_id, value, updated_at, source
        data_v2 = {
            "transcript": ["> Hello world", "Assistant: Hi there"],
            "history": [{}, {}],
            "model_info": {"model_id": "gpt-4"},
            "latest_summary": "Summary text"
        }
        rows = [
            ("/path/to/my-project", "conv123", json.dumps(data_v2), 1700000000000, "v2")
        ]
        mock_cursor.fetchall.return_value = rows

        sessions = kiro_sessionizer.get_sessions()

        assert len(sessions) == 1
        assert sessions[0]["id"] == "conv123"
        assert sessions[0]["key"] == "/path/to/my-project"
        assert sessions[0]["last_user_msg"] == "Hello world"
        assert "my-project" in sessions[0]["display"]

def test_timeline_grouping(capsys):
    now = datetime.now()
    today_ts = int(now.timestamp() * 1000)
    yesterday_ts = int((now - timedelta(days=1)).timestamp() * 1000)
    older_ts = int((now - timedelta(days=5)).timestamp() * 1000)
    older_date_str = (now - timedelta(days=5)).strftime("%Y-%m-%d")

    sessions = [
        {
            "key": "/p1",
            "updated_at": today_ts,
            "last_user_msg": "msg1",
            "display": "d1"
        },
        {
            "key": "/p2",
            "updated_at": yesterday_ts,
            "last_user_msg": "msg2",
            "display": "d2"
        },
        {
            "key": "/p3",
            "updated_at": older_ts,
            "last_user_msg": "msg3",
            "display": "d3"
        }
    ]

    with patch('kiro_sessionizer.get_sessions', return_value=sessions):
        kiro_sessionizer.show_timeline()
        captured = capsys.readouterr()
        assert "[ TODAY ]" in captured.out
        assert "[ YESTERDAY ]" in captured.out
        assert f"[ {older_date_str} ]" in captured.out
        assert "p1" in captured.out
        assert "p2" in captured.out
        assert "p3" in captured.out

def test_report_generation(capsys):
    today_ts = int(datetime.now().timestamp() * 1000)

    sessions = [
        {
            "key": "/project-alpha",
            "updated_at": today_ts,
            "last_user_msg": "initial msg",
            "data": {"latest_summary": "Finished feature X"},
            "display": "d1"
        },
        {
            "key": "/project-beta",
            "updated_at": today_ts,
            "last_user_msg": "fixed bug Y",
            "data": {},
            "display": "d2"
        }
    ]

    with patch('kiro_sessionizer.get_sessions', return_value=sessions):
        kiro_sessionizer.show_report()
        captured = capsys.readouterr()
        assert "Daily Accomplishments Report" in captured.out
        assert "# project-alpha" in captured.out
        assert "Finished feature X" in captured.out
        assert "# project-beta" in captured.out
        assert "fixed bug Y" in captured.out

@patch('kiro_sessionizer.update_session')
@patch('kiro_sessionizer.get_sessions')
def test_continue_command_logic(mock_get_sessions, mock_update, capsys):
    sessions = [
        {"key": "/work/frontend", "id": "1", "display": "d1"},
        {"key": "/work/backend", "id": "2", "display": "d2"}
    ]
    mock_get_sessions.return_value = sessions

    # Test basic continue (most recent)
    with patch('sys.argv', ['kiro_sessionizer.py', 'continue']):
        kiro_sessionizer.main()
        captured = capsys.readouterr()
        assert "cd /work/frontend && kiro-cli chat --resume" in captured.out

    # Test continue with project filter
    with patch('sys.argv', ['kiro_sessionizer.py', 'continue', '--project', 'back']):
        kiro_sessionizer.main()
        captured = capsys.readouterr()
        assert "cd /work/backend && kiro-cli chat --resume" in captured.out

    # Test continue with non-existent project
    with patch('sys.argv', ['kiro_sessionizer.py', 'continue', '--project', 'missing']):
        kiro_sessionizer.main()
        captured = capsys.readouterr()
        assert "No recent session found for project matching 'missing'" in captured.err
