import pytest
import sqlite3
import json
import os
import kiro_sessionizer
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

def test_strip_ansi():
    assert kiro_sessionizer.strip_ansi("\033[31mHello\033[0m") == "Hello"
    assert kiro_sessionizer.strip_ansi("Plain text") == "Plain text"

@patch('kiro_sessionizer.DB_PATH', 'test_data.sqlite3')
def test_get_sessions(tmp_path):
    db_path = str(tmp_path / "test_data.sqlite3")
    kiro_sessionizer.DB_PATH = db_path

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE conversations_v2 (key TEXT, conversation_id TEXT, value TEXT, created_at INTEGER, updated_at INTEGER)")
    cursor.execute("CREATE TABLE conversations (key TEXT, value TEXT)")

    val1 = json.dumps({"transcript": ["> user msg"], "history": [{}], "model_info": {"model_id": "test-model"}})
    cursor.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)", ("/path/to/proj1", "conv1", val1, 1000, 2000))

    conn.commit()
    conn.close()

    with patch('kiro_sessionizer.get_active_sessions', return_value={}):
        sessions = kiro_sessionizer.get_sessions()
        assert len(sessions) == 1
        assert sessions[0]["project"] == "proj1"
        assert sessions[0]["id"] == "conv1"

@patch('kiro_sessionizer.get_sessions')
def test_show_timeline(mock_get_sessions):
    today_ms = int(datetime.now().timestamp() * 1000)
    mock_get_sessions.return_value = [
        {
            "updated_at": today_ms,
            "project": "today_proj",
            "data": {"latest_summary": "Today summary"},
            "first_user_msg": "today msg",
            "preview": "today preview"
        }
    ]

    with patch('builtins.print') as mock_print:
        kiro_sessionizer.show_timeline()
        # Verify "TODAY" is in one of the print calls
        print_calls = [call.args[0] for call in mock_print.call_args_list if call.args]
        assert any("TODAY" in str(p) for p in print_calls)
        assert any("today_proj" in str(p) for p in print_calls)

@patch('kiro_sessionizer.get_sessions')
def test_show_report(mock_get_sessions):
    today = datetime.now()
    today_ms = int(today.timestamp() * 1000)
    mock_get_sessions.return_value = [
        {
            "updated_at": today_ms,
            "project": "report_proj",
            "data": {"latest_summary": "Report summary"},
            "first_user_msg": "msg",
            "preview": "prev"
        }
    ]

    with patch('builtins.print') as mock_print:
        kiro_sessionizer.show_report()
        print_calls = [call.args[0] for call in mock_print.call_args_list if call.args]
        assert any("report_proj" in str(p) for p in print_calls)
        assert any("Report summary" in str(p) for p in print_calls)

@patch('sqlite3.connect')
def test_fork_session(mock_connect, tmp_path):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    val = json.dumps({"conversation_id": "old", "transcript": []})
    mock_cursor.fetchone.return_value = (val,)

    new_id = kiro_sessionizer.fork_session("old", "/path")
    assert new_id is not None
    assert new_id != "old"
    assert mock_cursor.execute.call_count >= 2 # SELECT then INSERT

@patch('kiro_sessionizer.get_sessions')
def test_continue_project(mock_get_sessions):
    mock_get_sessions.return_value = [
        {"project": "proj1", "key": "/path1"},
        {"project": "other", "key": "/path2"}
    ]

    # Mocking main args
    with patch('sys.argv', ['kiro_sessionizer.py', 'continue', '--project', 'proj1']):
        with patch('kiro_sessionizer.update_session'):
            with patch('builtins.print') as mock_print:
                kiro_sessionizer.main()
                print_calls = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
                assert any("cd /path1" in p for p in print_calls)

@patch('kiro_sessionizer.get_sessions')
@patch('kiro_sessionizer.new_session')
def test_new_session_flow(mock_new_session, mock_get_sessions):
    mock_get_sessions.return_value = []

    with patch('sys.argv', ['kiro_sessionizer.py']):
        kiro_sessionizer.main()
        mock_new_session.assert_called_once()
