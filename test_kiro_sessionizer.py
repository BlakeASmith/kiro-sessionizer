import unittest
from unittest.mock import patch, MagicMock
import json
import sqlite3
import os
from datetime import datetime, timedelta
import kiro_sessionizer

class TestKiroSessionizer(unittest.TestCase):

    def test_strip_ansi(self):
        text = "\033[34mHello\033[0m"
        self.assertEqual(kiro_sessionizer.strip_ansi(text), "Hello")

    @patch("kiro_sessionizer.sqlite3.connect")
    @patch("kiro_sessionizer.os.path.exists")
    def test_get_sessions(self, mock_exists, mock_connect):
        mock_exists.return_value = True
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Mock rows: key, conversation_id, value, updated_at, source
        mock_cursor.fetchall.return_value = [
            ("/path/to/project1", "id1", json.dumps({
                "transcript": ["> User: hello", "Assistant: hi"],
                "history": [{}, {}],
                "model_info": {"model_id": "gpt-4"}
            }), 1600000000000, "v2")
        ]

        with patch("kiro_sessionizer.get_active_sessions", return_value={}):
            sessions = kiro_sessionizer.get_sessions()

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["key"], "/path/to/project1")
        self.assertEqual(sessions[0]["id"], "id1")

    @patch("kiro_sessionizer.get_sessions")
    def test_show_timeline(self, mock_get_sessions):
        today_ms = int(datetime.now().timestamp() * 1000)
        mock_get_sessions.return_value = [
            {
                "key": "/path/to/project1",
                "updated_at": today_ms,
                "pid": None,
                "data": {"latest_summary": "Today's work"}
            }
        ]

        with patch("sys.stdout", new=MagicMock()) as mock_stdout:
            kiro_sessionizer.show_timeline()
            # Verify "TODAY" and project name were printed
            output = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
            self.assertIn("TODAY", output)
            self.assertIn("project1", output)

    @patch("kiro_sessionizer.get_sessions")
    def test_generate_report(self, mock_get_sessions):
        today_ms = int(datetime.now().timestamp() * 1000)
        mock_get_sessions.return_value = [
            {
                "key": "/path/to/project1",
                "updated_at": today_ms,
                "pid": None,
                "data": {"latest_summary": "Implemented feature A"}
            }
        ]

        with patch("sys.stdout", new=MagicMock()) as mock_stdout:
            kiro_sessionizer.generate_report()
            output = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
            self.assertIn("Daily Accomplishment Report", output)
            self.assertIn("Implemented feature A", output)

    @patch("kiro_sessionizer.sqlite3.connect")
    def test_fork_session(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = [json.dumps({"conversation_id": "old_id", "transcript": []})]

        new_id = kiro_sessionizer.fork_session("old_id", "/path/to/project")

        self.assertIsNotNone(new_id)
        self.assertNotEqual(new_id, "old_id")
        # Verify INSERT was called
        self.assertTrue(any("INSERT INTO conversations_v2" in call.args[0] for call in mock_cursor.execute.call_args_list))

    @patch("kiro_sessionizer.sqlite3.connect")
    @patch("kiro_sessionizer.subprocess.Popen")
    @patch("kiro_sessionizer.os.path.exists")
    def test_new_session(self, mock_exists, mock_popen, mock_connect):
        mock_exists.return_value = True
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("/path/to/project1",)]

        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = ("/path/to/project1\n", None)
        mock_popen.return_value = mock_process

        project_path = kiro_sessionizer.new_session()
        self.assertEqual(project_path, "/path/to/project1")

    @patch("kiro_sessionizer.get_sessions")
    @patch("kiro_sessionizer.update_session")
    def test_continue_project(self, mock_update, mock_get_sessions):
        mock_get_sessions.return_value = [
            {"key": "/path/to/other", "updated_at": 2000, "source": "v2", "id": "id2"},
            {"key": "/path/to/myproj", "updated_at": 1000, "source": "v2", "id": "id1"}
        ]

        # Test with project filter
        with patch("sys.stdout", new=MagicMock()) as mock_stdout:
            with patch("sys.argv", ["kiro_sessionizer.py", "continue", "--project", "myproj"]):
                kiro_sessionizer.main()
                output = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
                self.assertIn("cd /path/to/myproj", output)

if __name__ == "__main__":
    unittest.main()
