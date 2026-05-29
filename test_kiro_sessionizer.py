import unittest
from unittest.mock import patch, MagicMock, mock_open
import json
import sqlite3
import os
import kiro_sessionizer

class TestKiroSessionizer(unittest.TestCase):

    def setUp(self):
        self.db_path = "test_data.sqlite3"
        kiro_sessionizer.DB_PATH = self.db_path
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE conversations_v2 (key TEXT, conversation_id TEXT, value TEXT, created_at INTEGER, updated_at INTEGER, PRIMARY KEY (key, conversation_id))")
        cursor.execute("CREATE TABLE conversations (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    @patch('kiro_sessionizer.get_active_sessions')
    def test_get_sessions(self, mock_active):
        mock_active.return_value = {}
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        val = json.dumps({"transcript": ["> User: test"], "history": [], "model_info": {}})
        cursor.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)", ("/path/to/proj", "uuid1", val, 1000, 2000))
        conn.commit()
        conn.close()

        sessions = kiro_sessionizer.get_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["id"], "uuid1")
        self.assertEqual(sessions[0]["project"], "proj")

    def test_fork_session(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        val = json.dumps({"conversation_id": "old", "transcript": ["> User: test"]})
        cursor.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)", ("/path/proj", "old", val, 1000, 1000))
        conn.commit()
        conn.close()

        new_id = kiro_sessionizer.fork_session("old", "/path/proj")
        self.assertIsNotNone(new_id)
        self.assertNotEqual(new_id, "old")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM conversations_v2 WHERE conversation_id = ?", (new_id,))
        row = cursor.fetchone()
        data = json.loads(row[0])
        self.assertEqual(data["conversation_id"], new_id)
        self.assertIn("[Session forked from old]", data["transcript"][-1])
        conn.close()

    @patch('subprocess.check_output')
    def test_get_active_sessions_optimized(self, mock_output):
        # Mock pgrep
        def side_effect(cmd, **kwargs):
            if "pgrep" in cmd:
                if "kiro-cli" in cmd: return "123\n"
                if "bun" in cmd: return "456\n"
            if "lsof" in cmd:
                return "p123\nn/path1\np456\nn/path2\n"
            return ""

        mock_output.side_effect = side_effect

        # We need to mock os.path.exists and glob to avoid hitting the filesystem for lock files
        with patch('os.path.exists') as mock_exists, patch('glob.glob') as mock_glob:
            mock_exists.return_value = False # No lock files
            active = kiro_sessionizer.get_active_sessions()

        self.assertEqual(active["/path1"], 123)
        self.assertEqual(active["/path2"], 456)

    @patch('kiro_sessionizer.get_sessions')
    def test_continue_project_matching(self, mock_get):
        mock_get.return_value = [
            {"key": "/users/dev/my-project", "display": "...", "id": "1", "updated_at": 1000, "source": "v2"},
            {"key": "/users/dev/other-proj", "display": "...", "id": "2", "updated_at": 500, "source": "v2"}
        ]

        # Mock main and argparse
        with patch('sys.argv', ['kiro_sessionizer', 'continue', '--project', 'other']):
            with patch('kiro_sessionizer.update_session'):
                with patch('sys.stdout', new_callable=MagicMock) as mock_stdout:
                    kiro_sessionizer.main()
                    output = mock_stdout.write.call_args_list[0][0][0]
                    self.assertIn("other-proj", output)

if __name__ == '__main__':
    unittest.main()
