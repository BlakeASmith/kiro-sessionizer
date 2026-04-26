import unittest
from unittest.mock import patch, MagicMock
import os
import json
import kiro_sessionizer

class TestKiroSessionizer(unittest.TestCase):

    def setUp(self):
        # Sample session data
        self.sample_value = json.dumps({
            "transcript": ["> Hello", "Assistant: Hi there"],
            "history": [{"user": "Hello"}, {"assistant": "Hi there"}],
            "model_info": {"model_id": "test-model"},
            "latest_summary": "Testing session"
        })
        self.sample_session = {
            "key": "/path/to/project",
            "conversation_id": "uuid-123",
            "value": self.sample_value,
            "updated_at": 1700000000000,
            "source": "v2"
        }

    @patch('kiro_sessionizer.sqlite3.connect')
    @patch('kiro_sessionizer.os.path.exists')
    def test_get_sessions(self, mock_exists, mock_connect):
        mock_exists.return_value = True
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_cursor = mock_conn.cursor.return_value
        mock_cursor.fetchall.return_value = [
            ("/path/to/project", "uuid-123", self.sample_value, 1700000000000, "v2")
        ]

        sessions = kiro_sessionizer.get_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]['id'], 'uuid-123')
        self.assertEqual(sessions[0]['last_user_msg'], 'Hello')

    @patch('kiro_sessionizer.get_sessions')
    def test_show_timeline(self, mock_get_sessions):
        mock_get_sessions.return_value = [
            {
                "updated_at": 1700000000000,
                "display": "session-display",
                "key": "/path/to/proj"
            }
        ]
        with patch('builtins.print') as mock_print:
            kiro_sessionizer.show_timeline()
            # Verify it printed a header and the session
            mock_print.assert_any_call("\n\033[1m\033[33m--- 2023-11-14 ---\033[0m")
            mock_print.assert_any_call("session-display")

    @patch('kiro_sessionizer.get_sessions')
    def test_generate_report_no_activity(self, mock_get_sessions):
        # Return a session from the past
        mock_get_sessions.return_value = [{
            "updated_at": 1000000000,
            "data": {},
            "key": "/path/to/old"
        }]
        with patch('builtins.print') as mock_print:
            kiro_sessionizer.generate_report()
            mock_print.assert_called_with("No activity recorded for today.")

    @patch('kiro_sessionizer.subprocess.run')
    @patch('kiro_sessionizer.subprocess.Popen')
    def test_new_session_agent_selection(self, mock_popen, mock_run):
        # Mock agent list
        mock_run.return_value = MagicMock(returncode=0, stdout="AGENT\n---\nengineer\narchitect")

        # Mock fzf selection
        mock_process = MagicMock()
        mock_popen.return_value = mock_process
        mock_process.communicate.return_value = ("engineer\n", None)
        mock_process.returncode = 0

        with patch('builtins.print') as mock_print:
            kiro_sessionizer.new_session()
            mock_print.assert_called_with("kiro-cli chat --agent engineer")

    @patch('kiro_sessionizer.get_sessions')
    def test_continue_with_project_filter(self, mock_get_sessions):
        mock_get_sessions.return_value = [
            {"key": "/path/to/my-project", "id": "1", "source": "v2"},
            {"key": "/path/to/other-project", "id": "2", "source": "v2"}
        ]

        with patch('kiro_sessionizer.update_session'), \
             patch('builtins.print') as mock_print:

            # Mock args
            args = MagicMock()
            args.command = "continue"
            args.project = "my-project"

            with patch('kiro_sessionizer.argparse.ArgumentParser.parse_args', return_value=args):
                kiro_sessionizer.main()

            # Should cd into my-project
            mock_print.assert_any_call("cd /path/to/my-project && kiro-cli chat --resume")

if __name__ == '__main__':
    unittest.main()
