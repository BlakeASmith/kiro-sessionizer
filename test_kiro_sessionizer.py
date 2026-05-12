import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
import json
import os
import io
import sys
import kiro_sessionizer

class TestKiroSessionizer(unittest.TestCase):
    def test_strip_ansi(self):
        self.assertEqual(kiro_sessionizer.strip_ansi("\033[34mHello\033[0m"), "Hello")
        self.assertEqual(kiro_sessionizer.strip_ansi("Plain"), "Plain")

    @patch('kiro_sessionizer.get_sessions')
    def test_show_timeline(self, mock_get_sessions):
        now = datetime.now()
        today_ms = int(now.timestamp() * 1000)
        mock_get_sessions.return_value = [
            {"updated_at": today_ms, "display": "●\tProj1\tDate\tModel\t10\tPreview1\tKey1\tPID1\tID1"},
            {"updated_at": 0, "display": " \tProjL\tDate\tModel\t0\tPreviewL\tKeyL\tPIDL\tIDL"},
        ]

        captured_output = io.StringIO()
        sys.stdout = captured_output
        kiro_sessionizer.show_timeline()
        sys.stdout = sys.__stdout__

        output = captured_output.getvalue()
        self.assertIn("--- TODAY ---", output)
        self.assertIn("--- LEGACY / UNKNOWN ---", output)
        self.assertIn("Proj1", output)

    @patch('kiro_sessionizer.get_sessions')
    def test_generate_report(self, mock_get_sessions):
        now = datetime.now()
        today_ms = int(now.timestamp() * 1000)
        mock_get_sessions.return_value = [
            {
                "updated_at": today_ms,
                "key": "/path/to/ProjA",
                "data": {"latest_summary": "Did feature A"},
                "last_user_msg": "User message"
            }
        ]

        captured_output = io.StringIO()
        sys.stdout = captured_output
        kiro_sessionizer.generate_report()
        sys.stdout = sys.__stdout__

        output = captured_output.getvalue()
        self.assertIn("Daily Accomplishment Report", output)
        self.assertIn("Project: ProjA", output)
        self.assertIn("Did feature A", output)

    @patch('kiro_sessionizer.os.path.exists')
    @patch('kiro_sessionizer.sqlite3.connect')
    @patch('kiro_sessionizer.get_active_sessions')
    def test_get_sessions_metadata(self, mock_active, mock_connect, mock_exists):
        mock_exists.return_value = True
        mock_active.return_value = {}
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_cursor = mock_conn.cursor.return_value

        mock_data = {
            "transcript": ["> User: Hello", "Assistant: Hi"],
            "history": [{}, {}],
            "model_info": {"model_id": "gpt-4"},
            "latest_summary": "Greeting session"
        }
        mock_cursor.fetchall.return_value = [
            ("/path/to/project", "uuid-123", json.dumps(mock_data), 1672531200000, "v2")
        ]

        sessions = kiro_sessionizer.get_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["last_user_msg"], "Hello")

if __name__ == "__main__":
    unittest.main()
