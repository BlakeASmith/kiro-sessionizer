import os
import sqlite3
import json
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

# Import module
import kiro_sessionizer

class TestKiroSessionizer(unittest.TestCase):
    def setUp(self):
        # Create a temp sqlite DB
        self.db_path = "test_data.sqlite3"
        kiro_sessionizer.DB_PATH = self.db_path

        # Ensure a clean database for each test
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()

        # Setup tables
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations_v2 (
                key TEXT,
                conversation_id TEXT,
                value TEXT,
                created_at INTEGER,
                updated_at INTEGER,
                PRIMARY KEY (key, conversation_id)
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                key TEXT,
                value TEXT
            )
        """)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    @patch("kiro_sessionizer.get_active_sessions")
    @patch("os.path.exists")
    def test_get_sessions(self, mock_exists, mock_active):
        # Mock active sessions
        mock_active.return_value = {"/path/to/proj1": 12345}

        # Mock DB existence
        def side_effect(path):
            if path == self.db_path:
                return True
            return os.path.exists(path)
        mock_exists.side_effect = side_effect

        # Insert test data
        v2_value = {
            "transcript": ["> user message", "Assistant: response"],
            "history": [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}],
            "model_info": {"model_id": "test-model"},
            "file_line_tracker": {"/path/to/proj1/file1.py": {}}
        }
        v1_value = {
            "transcript": ["> legacy message", "Assistant: legacy response"],
            "history": [{"role": "user", "content": "legacy"}],
            "model_info": "legacy-model",
            "file_line_tracker": {"file2.py": {}}
        }

        now_ms = int(datetime.now().timestamp() * 1000)
        self.cursor.execute(
            "INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
            ("/path/to/proj1", "conv-v2-id", json.dumps(v2_value), now_ms, now_ms)
        )
        self.cursor.execute(
            "INSERT INTO conversations VALUES (?, ?)",
            ("/path/to/proj2", json.dumps(v1_value))
        )
        self.conn.commit()

        sessions = kiro_sessionizer.get_sessions()
        self.assertEqual(len(sessions), 2)

        # First session should be v2 (sorted by updated_at desc)
        self.assertEqual(sessions[0]["id"], "conv-v2-id")
        self.assertEqual(sessions[0]["source"], "v2")
        self.assertEqual(sessions[0]["pid"], 12345)

        # Second session should be v1
        self.assertEqual(sessions[1]["id"], "legacy")
        self.assertEqual(sessions[1]["source"], "v1")

    @patch("kiro_sessionizer.get_active_sessions")
    @patch("os.path.exists")
    def test_show_stats(self, mock_exists, mock_active):
        mock_active.return_value = {}
        def side_effect(path):
            if path == self.db_path:
                return True
            return os.path.exists(path)
        mock_exists.side_effect = side_effect

        v2_value = {
            "transcript": ["> user message"],
            "history": [{"role": "user"}],
            "model_info": {"model_id": "test-model"},
            "file_line_tracker": {"/path/to/proj1/file1.py": {}}
        }
        now_ms = int(datetime.now().timestamp() * 1000)
        self.cursor.execute(
            "INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
            ("/path/to/proj1", "conv-v2-id", json.dumps(v2_value), now_ms, now_ms)
        )
        self.conn.commit()

        # Capture output of show_stats
        with patch("sys.stdout") as mock_stdout:
            kiro_sessionizer.show_stats()
            # Verify stdout prints stats
            calls = [call[0][0] for call in mock_stdout.write.call_args_list if call[0][0].strip()]
            joined_output = kiro_sessionizer.strip_ansi("".join(calls))
            self.assertIn("test-model", joined_output)
            self.assertIn("file1.py", joined_output)

    @patch("kiro_sessionizer.get_active_sessions")
    @patch("os.path.exists")
    @patch("subprocess.Popen")
    def test_restore_session_files(self, mock_popen, mock_exists, mock_active):
        mock_active.return_value = {}
        # Ensure paths exist
        def side_effect(path):
            if path in [self.db_path, "/path/to/proj1/file1.py", "/path/to/proj1"]:
                return True
            return os.path.exists(path)
        mock_exists.side_effect = side_effect

        v2_value = {
            "transcript": [],
            "history": [],
            "file_line_tracker": {"file1.py": {}}
        }
        now_ms = int(datetime.now().timestamp() * 1000)
        self.cursor.execute(
            "INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
            ("/path/to/proj1", "conv-v2-id", json.dumps(v2_value), now_ms, now_ms)
        )
        self.conn.commit()

        # Test single file restore (no fzf needed, opens directly)
        kiro_sessionizer.restore_session_files("conv-v2-id", "/path/to/proj1", editor_arg="code")
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        self.assertIn("code", args[0])
        self.assertIn("/path/to/proj1/file1.py", args[0])

    @patch("kiro_sessionizer.is_fzf_tmux_supported")
    @patch("subprocess.Popen")
    @patch("os.path.exists")
    def test_jump_to_project(self, mock_exists, mock_popen, mock_fzf_tmux):
        mock_fzf_tmux.return_value = False
        def side_effect(path):
            if path in [self.db_path, "/path/to/proj1", "/path/to/proj2"]:
                return True
            return os.path.exists(path)
        mock_exists.side_effect = side_effect

        # Insert v2 and v1 path
        self.cursor.execute(
            "INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
            ("/path/to/proj1", "id1", "{}", 0, 1000)
        )
        self.cursor.execute(
            "INSERT INTO conversations VALUES (?, ?)",
            ("/path/to/proj2", "{}")
        )
        self.conn.commit()

        # Mock subprocess Popen for fzf
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = ("proj1\t/path/to/proj1\n", None)
        mock_popen.return_value = mock_process

        with patch("sys.stdout") as mock_stdout:
            kiro_sessionizer.jump_to_project()
            calls = [call[0][0] for call in mock_stdout.write.call_args_list if call[0][0].strip()]
            self.assertTrue(any("cd /path/to/proj1" in c for c in calls))

    @patch("os.path.exists")
    def test_generate_journal(self, mock_exists):
        def side_effect(path):
            if path == self.db_path:
                return True
            return os.path.exists(path)
        mock_exists.side_effect = side_effect

        v2_value = {
            "transcript": ["> First query here", "Assistant: some reply"],
            "history": [],
            "latest_summary": "Summary of work done"
        }
        self.cursor.execute(
            "INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
            ("/path/to/proj1", "id1", json.dumps(v2_value), 0, 1000)
        )
        self.conn.commit()

        with patch("sys.stdout") as mock_stdout:
            kiro_sessionizer.generate_journal("/path/to/proj1")
            calls = [call[0][0] for call in mock_stdout.write.call_args_list if call[0][0].strip()]
            joined_output = kiro_sessionizer.strip_ansi("".join(calls))
            self.assertIn("First Query: First query here", joined_output)
            self.assertIn("Summary: Summary of work done", joined_output)

    @patch("kiro_sessionizer.get_active_sessions")
    @patch("os.path.exists")
    def test_prune_sessions(self, mock_exists, mock_active):
        mock_active.return_value = {}
        def side_effect(path):
            if path == self.db_path:
                return True
            return os.path.exists(path)
        mock_exists.side_effect = side_effect

        # Insert extremely old session (Unix epoch) and relatively new one
        old_val = {"history": []} # 0 msgs
        new_val = {"history": [{"role": "user"}]} # 1 msg

        # old session (age > 30 days)
        self.cursor.execute(
            "INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
            ("/path/to/proj1", "old-id", json.dumps(old_val), 1000, 1000)
        )
        # new session
        now_ms = int(datetime.now().timestamp() * 1000)
        self.cursor.execute(
            "INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
            ("/path/to/proj1", "new-id", json.dumps(new_val), now_ms, now_ms)
        )
        self.conn.commit()

        # Prune with age=30 days, min_messages=2. This should match old-id, but not new-id
        kiro_sessionizer.prune_sessions(days=30, min_messages=2, apply_deletions=True, force=True)

        # Check DB
        self.cursor.execute("SELECT conversation_id FROM conversations_v2")
        remaining_ids = [r[0] for r in self.cursor.fetchall()]
        self.assertNotIn("old-id", remaining_ids)
        self.assertIn("new-id", remaining_ids)

    @patch("kiro_sessionizer.get_active_sessions")
    @patch("os.path.exists")
    def test_generate_report(self, mock_exists, mock_active):
        mock_active.return_value = {}
        def side_effect(path):
            if path == self.db_path:
                return True
            return os.path.exists(path)
        mock_exists.side_effect = side_effect

        v2_value = {
            "transcript": ["> query 1"],
            "history": [],
            "latest_summary": "standup summary",
            "file_line_tracker": {"file.txt": {}}
        }
        now_ms = int(datetime.now().timestamp() * 1000)
        self.cursor.execute(
            "INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
            ("/path/to/proj1", "id1", json.dumps(v2_value), now_ms, now_ms)
        )
        self.conn.commit()

        with patch("sys.stdout") as mock_stdout:
            kiro_sessionizer.generate_report(days=1)
            calls = [call[0][0] for call in mock_stdout.write.call_args_list if call[0][0].strip()]
            joined_output = kiro_sessionizer.strip_ansi("".join(calls))
            self.assertIn("standup summary", joined_output)
            self.assertIn("file.txt", joined_output)

    @patch("kiro_sessionizer.get_active_sessions")
    @patch("os.path.exists")
    def test_draft_commit(self, mock_exists, mock_active):
        mock_active.return_value = {}
        def side_effect(path):
            if path == self.db_path:
                return True
            return os.path.exists(path)
        mock_exists.side_effect = side_effect

        v2_value = {
            "transcript": [],
            "history": [],
            "latest_summary": "Implements core feature",
            "file_line_tracker": {"file.txt": {}}
        }
        now_ms = int(datetime.now().timestamp() * 1000)
        self.cursor.execute(
            "INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
            ("/path/to/proj1", "id1", json.dumps(v2_value), now_ms, now_ms)
        )
        self.conn.commit()

        with patch("sys.stdout") as mock_stdout:
            kiro_sessionizer.draft_commit()
            calls = [call[0][0] for call in mock_stdout.write.call_args_list if call[0][0].strip()]
            joined_output = kiro_sessionizer.strip_ansi("".join(calls))
            self.assertIn("Implements core feature", joined_output)
            self.assertIn("- file.txt", joined_output)

if __name__ == "__main__":
    unittest.main()
