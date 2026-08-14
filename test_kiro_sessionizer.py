import os
import sys
import json
import sqlite3
import pytest
from unittest.mock import MagicMock, patch
import kiro_sessionizer

@pytest.fixture
def test_env(tmp_path):
    # Setup paths
    db_file = tmp_path / "data.sqlite3"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    # Save original values
    orig_db = kiro_sessionizer.DB_PATH
    orig_dir = kiro_sessionizer.SESSIONS_DIR

    kiro_sessionizer.DB_PATH = str(db_file)
    kiro_sessionizer.SESSIONS_DIR = str(sessions_dir)

    # Initialize DB
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE conversations_v2 (
        key TEXT,
        conversation_id TEXT,
        value TEXT,
        created_at INTEGER,
        updated_at INTEGER,
        PRIMARY KEY (key, conversation_id)
    )
    """)
    cursor.execute("""
    CREATE TABLE conversations (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    # Populate dummy conversations_v2
    val_a = {
        "conversation_id": "uuid-a-1234",
        "history": [{}, {}],
        "transcript": [
            "> Implement login",
            "Assistant: Sure, here is how you do it",
            "[Tool uses: fs_write]",
            "> Fix some bugs",
            "Assistant: Let's investigate"
        ],
        "latest_summary": "Implemented login and fixed minor bugs.",
        "model_info": {
            "model_id": "anthropic.claude-v3"
        },
        "file_line_tracker": {
            "src/login.py": [1, 2],
            "src/utils.py": [10]
        }
    }
    cursor.execute(
        "INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
        ("/home/user/project_a", "uuid-a-1234", json.dumps(val_a), 1711929600000, 1711933200000)
    )

    # Populate dummy conversations (legacy)
    val_b = {
        "conversation_id": "legacy",
        "history": [],
        "transcript": [
            "> Hello world",
            "Assistant: Legacy greeting"
        ],
        "latest_summary": "Legacy session greeting.",
        "model_info": {
            "model_id": "legacy-model"
        },
        "file_line_tracker": {
            "README.md": [1]
         }
    }
    cursor.execute(
        "INSERT INTO conversations VALUES (?, ?)",
        ("/home/user/project_b", json.dumps(val_b))
    )

    conn.commit()
    conn.close()

    yield {
        "db_path": str(db_file),
        "sessions_dir": str(sessions_dir),
        "project_a": "/home/user/project_a",
        "project_b": "/home/user/project_b",
    }

    # Restore originals
    kiro_sessionizer.DB_PATH = orig_db
    kiro_sessionizer.SESSIONS_DIR = orig_dir


def test_get_sessions(test_env):
    sessions = kiro_sessionizer.get_sessions()
    assert len(sessions) == 2
    # Sorted by updated_at descending, so v2 should be first
    assert sessions[0]["id"] == "uuid-a-1234"
    assert sessions[0]["key"] == test_env["project_a"]
    assert sessions[1]["id"] == "legacy"
    assert sessions[1]["key"] == test_env["project_b"]


def test_run_preview(test_env, capsys):
    kiro_sessionizer.run_preview(test_env["project_a"], "uuid-a-1234", "", "project_a")
    captured = capsys.readouterr().out
    clean_out = kiro_sessionizer.strip_ansi(captured)

    assert "PROJECT: project_a" in clean_out
    assert "MODEL:   anthropic.claude-v3" in clean_out
    assert "MESSAGES: 2" in clean_out
    assert "FIRST QUERY:" in clean_out
    assert "SUMMARY:" in clean_out
    assert "Implemented login" in clean_out
    assert "FILES TOUCHED:" in clean_out
    assert "login.py" in clean_out


def test_stats(test_env, capsys):
    kiro_sessionizer.show_stats()
    captured = capsys.readouterr().out
    clean_out = kiro_sessionizer.strip_ansi(captured)

    assert "Total Sessions:  2" in clean_out
    assert "Total Messages:  2" in clean_out
    assert "Top Projects:" in clean_out
    assert "project_a" in clean_out
    assert "project_b" in clean_out
    assert "Top Files Discussed:" in clean_out
    assert "login.py" in clean_out
    assert "README.md" in clean_out


def test_search_sessions(test_env):
    # Search for login
    results = kiro_sessionizer.search_sessions("login")
    assert len(results) == 1
    assert results[0]["id"] == "uuid-a-1234"
    assert "login" in kiro_sessionizer.strip_ansi(results[0]["display"])


def test_draft_commit(test_env, capsys):
    kiro_sessionizer.draft_commit()
    captured = capsys.readouterr().out
    clean_out = kiro_sessionizer.strip_ansi(captured)

    assert "Drafted Commit Message" in clean_out
    assert "docs/feat/fix: implemented login and fixed minor bugs" in clean_out
    assert "Files affected:" in clean_out
    assert "- login.py" in clean_out
    assert "- utils.py" in clean_out


def test_generate_report(test_env, capsys):
    # Generates a report looking back 10000 days to include all mock entries
    kiro_sessionizer.generate_report(10000)
    captured = capsys.readouterr().out
    clean_out = kiro_sessionizer.strip_ansi(captured)

    assert "Work Standup Report" in clean_out
    assert "[project_a]" in clean_out
    assert "anthropic.claude-v3" in clean_out
    assert "Initial Query" in clean_out
    assert "Implement login" in clean_out
    assert "Implemented login and fixed minor bugs." in clean_out


def test_generate_journal(test_env, capsys):
    kiro_sessionizer.generate_journal(test_env["project_a"])
    captured = capsys.readouterr().out
    clean_out = kiro_sessionizer.strip_ansi(captured)

    assert "Project Journal: project_a" in clean_out
    assert "First Query" in clean_out
    assert "Implement login" in clean_out
    assert "Implemented login and fixed minor bugs." in clean_out


def test_prune_sessions_dry_run(test_env, capsys):
    # Dry run should list sessions but not delete
    kiro_sessionizer.prune_sessions(days=30, min_messages=10, dry_run=True, force=True)
    captured = capsys.readouterr().out
    clean_out = kiro_sessionizer.strip_ansi(captured)

    assert "Found 2 sessions to prune" in clean_out
    assert "DRY RUN" in clean_out

    # Verify sessions are still in DB
    sessions = kiro_sessionizer.get_sessions()
    assert len(sessions) == 2


def test_prune_sessions_apply(test_env, capsys):
    # Apply prune with criteria that matches both
    kiro_sessionizer.prune_sessions(days=0, min_messages=10, dry_run=False, force=True)
    captured = capsys.readouterr().out
    clean_out = kiro_sessionizer.strip_ansi(captured)

    assert "Successfully pruned 2 sessions" in clean_out

    # Verify database is empty of conversations
    sessions = kiro_sessionizer.get_sessions()
    assert len(sessions) == 0


def test_delete_sessions(test_env):
    kiro_sessionizer.delete_sessions([("uuid-a-1234", test_env["project_a"])])
    sessions = kiro_sessionizer.get_sessions()
    assert len(sessions) == 1
    assert sessions[0]["id"] == "legacy"


@patch("os.path.exists")
@patch("os.path.isfile")
@patch("subprocess.Popen")
def test_restore_session_files(mock_popen, mock_isfile, mock_exists, test_env, capsys):
    # Set exists and isfile to True so mock files are recognized
    mock_exists.side_effect = lambda path: True if "data.sqlite3" in path or "login.py" in path or "utils.py" in path else False
    mock_isfile.return_value = True

    # Call restore
    kiro_sessionizer.restore_session_files("uuid-a-1234", key=test_env["project_a"], editor="code", quiet=False)
    captured = capsys.readouterr().out
    assert "Restoring 2 files in code..." in captured
    mock_popen.assert_called_once()
    args, kwargs = mock_popen.call_args
    assert "code" in args[0]
    assert any("login.py" in f for f in args[0])


@patch("subprocess.Popen")
def test_jump_to_project_empty(mock_popen, test_env, capsys):
    # Since mocked paths won't exist on physical test runner, expect "No valid project directories found"
    kiro_sessionizer.jump_to_project()
    captured = capsys.readouterr().err
    assert "No valid project directories found." in captured
