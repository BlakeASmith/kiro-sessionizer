import pytest
from unittest.mock import patch, MagicMock
import json
import os
from datetime import datetime, timedelta
import kiro_sessionizer

def test_strip_ansi():
    text = "\033[34mBlue\033[0m Text"
    assert kiro_sessionizer.strip_ansi(text) == "Blue Text"

    complex_text = "\033[1mBold\t\033[32mGreen\033[0m"
    assert kiro_sessionizer.strip_ansi(complex_text) == "Bold\tGreen"

@patch("kiro_sessionizer.sqlite3.connect")
@patch("kiro_sessionizer.os.path.exists")
@patch("kiro_sessionizer.get_active_sessions")
def test_get_sessions(mock_active, mock_exists, mock_connect):
    mock_exists.return_value = True
    mock_active.return_value = {}

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    # Mock DB rows
    # key, conversation_id, value, updated_at, source
    mock_data = {
        "transcript": ["> Hello", "Assistant: Hi"],
        "history": [{}, {}],
        "model_info": {"model_id": "gpt-4"}
    }
    mock_cursor.fetchall.return_value = [
        ("/path/to/project", "conv-1", json.dumps(mock_data), 1700000000000, "v2")
    ]

    sessions = kiro_sessionizer.get_sessions()

    assert len(sessions) == 1
    assert sessions[0]["id"] == "conv-1"
    assert "gpt-4" in sessions[0]["display"]
    assert sessions[0]["updated_at"] == 1700000000000
    assert sessions[0]["data"]["model_info"]["model_id"] == "gpt-4"

@patch("kiro_sessionizer.get_sessions")
def test_generate_report_no_sessions(mock_get):
    mock_get.return_value = []
    with patch("sys.stderr.write") as mock_stderr:
        kiro_sessionizer.generate_report()
        # Verify it doesn't crash and prints message to stderr
        calls = [call.args[0] for call in mock_stderr.call_args_list]
        assert any("No sessions found for today" in c for c in calls)

@patch("kiro_sessionizer.get_sessions")
def test_report_content(mock_get):
    today_ms = int(datetime.now().timestamp() * 1000)
    mock_get.return_value = [
        {
            "key": "/p/proj1",
            "updated_at": today_ms,
            "data": {
                "latest_summary": "Finished the feature",
                "transcript": []
            }
        }
    ]

    with patch("builtins.print") as mock_print:
        kiro_sessionizer.generate_report()
        # Check if project and summary are printed
        printed = [call.args[0] for call in mock_print.call_args_list if call.args]
        assert any("proj1" in p for p in printed)
        assert any("Finished the feature" in p for p in printed)

def test_timeline_grouping():
    # This is harder to test because it calls select_session which uses subprocess
    # But we can verify the grouping logic by mocking select_session
    today_ms = int(datetime.now().timestamp() * 1000)
    yesterday_ms = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)

    sessions = [
        {"display": "today", "updated_at": today_ms},
        {"display": "yesterday", "updated_at": yesterday_ms}
    ]

    with patch("kiro_sessionizer.select_session") as mock_select:
        kiro_sessionizer.show_timeline(sessions)

        # Verify select_session was called with headers
        args, _ = mock_select.call_args
        timeline_list = args[0]

        headers = [s["display"] for s in timeline_list if s.get("is_header")]
        assert any("TODAY" in h for h in headers)
        assert any("YESTERDAY" in h for h in headers)

@patch("kiro_sessionizer.subprocess.run")
@patch("kiro_sessionizer.subprocess.Popen")
def test_new_session_agent_selection(mock_popen, mock_run):
    # Mock agent list
    mock_run.return_value = MagicMock(stdout="agent1\nagent2\n", check=True)

    # Mock fzf selection
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("agent1\n", None)
    mock_proc.returncode = 0
    mock_popen.return_value = mock_proc

    cmd = kiro_sessionizer.new_session()
    assert cmd == "kiro-cli chat --agent agent1"

@patch("kiro_sessionizer.get_sessions")
@patch("kiro_sessionizer.update_session")
def test_continue_project_filter(mock_update, mock_get):
    mock_get.return_value = [
        {"key": "/p/web-app", "id": "1"},
        {"key": "/p/api-server", "id": "2"}
    ]

    # Mock argparse and main execution
    from argparse import Namespace
    args = Namespace(command="continue", project="api")

    with patch("argparse.ArgumentParser.parse_args", return_value=args):
        with patch("builtins.print") as mock_print:
            kiro_sessionizer.main()
            printed = mock_print.call_args[0][0]
            assert "api-server" in printed
            assert "kiro-cli chat --resume" in printed
