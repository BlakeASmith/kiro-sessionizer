import unittest
from unittest.mock import patch, MagicMock
import io
from datetime import datetime, timedelta
import os
import json

from kiro_sessionizer import strip_ansi, show_timeline, generate_report

class TestKiroSessionizer(unittest.TestCase):

    def test_strip_ansi(self):
        text = "\033[34mHello\033[0m"
        self.assertEqual(strip_ansi(text), "Hello")

    @patch('kiro_sessionizer.get_sessions')
    @patch('sys.stdout', new_callable=io.StringIO)
    def test_show_timeline(self, mock_stdout, mock_get_sessions):
        now = datetime.now()
        today_ms = int(now.timestamp() * 1000)
        yesterday_ms = int((now - timedelta(days=1)).timestamp() * 1000)
        older_ms = int((now - timedelta(days=5)).timestamp() * 1000)

        mock_get_sessions.return_value = [
            {
                "key": "/path/to/today_proj",
                "updated_at": today_ms,
                "data": {"latest_summary": "Today's work", "transcript": []}
            },
            {
                "key": "/path/to/yesterday_proj",
                "updated_at": yesterday_ms,
                "data": {"latest_summary": "Yesterday's work", "transcript": []}
            },
            {
                "key": "/path/to/older_proj",
                "updated_at": older_ms,
                "data": {"latest_summary": "Older work", "transcript": []}
            },
            {
                "key": "/path/to/legacy_proj",
                "updated_at": 0,
                "data": {"transcript": ["> Hello"]}
            }
        ]

        show_timeline()
        output = mock_stdout.getvalue()

        self.assertIn("--- TODAY ---", output)
        self.assertIn("today_proj", output)
        self.assertIn("Today's work", output)

        self.assertIn("--- YESTERDAY ---", output)
        self.assertIn("yesterday_proj", output)

        self.assertIn("--- LEGACY / UNKNOWN ---", output)
        self.assertIn("legacy_proj", output)

    @patch('kiro_sessionizer.get_sessions')
    @patch('sys.stdout', new_callable=io.StringIO)
    def test_generate_report(self, mock_stdout, mock_get_sessions):
        now = datetime.now()
        today_ms = int(now.timestamp() * 1000)

        mock_get_sessions.return_value = [
            {
                "key": "/path/to/projA",
                "updated_at": today_ms,
                "data": {"latest_summary": "Feature X implemented", "transcript": []}
            },
            {
                "key": "/path/to/projA",
                "updated_at": today_ms,
                "data": {"latest_summary": None, "transcript": ["> Fix bug Y", "Assistant: Done"]}
            },
            {
                "key": "/path/to/projB",
                "updated_at": today_ms,
                "data": {"latest_summary": "Refactoring", "transcript": []}
            }
        ]

        generate_report()
        output = mock_stdout.getvalue()

        self.assertIn("# Daily Activity Report", output)
        self.assertIn("## projA", output)
        self.assertIn("- Feature X implemented", output)
        self.assertIn("- Fix bug Y", output)
        self.assertIn("## projB", output)
        self.assertIn("- Refactoring", output)

if __name__ == '__main__':
    unittest.main()
