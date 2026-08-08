import os
import json
import sqlite3
import pytest
import sys
from unittest.mock import patch, MagicMock
from datetime import datetime

# Configure environment before import
DB_FILE = "test_data.sqlite3"
os.environ["KIRO_DB_PATH"] = DB_FILE

import kiro_sessionizer

@pytest.fixture(autouse=True)
def setup_db():
    # Remove existing test DB if any
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)

    # Connect and create tables
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversations_v2 (
        key TEXT,
        conversation_id TEXT,
        value TEXT,
        created_at INTEGER,
        updated_at INTEGER,
        PRIMARY KEY (key, conversation_id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")

    # Insert mock conversations_v2 data
    v2_value = {
        "conversation_id": "test-v2-uuid-1",
        "history": [
            {
                "user": {"content": {"Prompt": {"prompt": "how to code"}}},
                "assistant": {"ToolUse": {"content": "with python"}}
            }
        ],
        "transcript": [
            "> how to code",
            "with python"
        ],
        "latest_summary": "Taught python coding basics.",
        "model_info": {
            "model_id": "anthropic.claude-3-sonnet"
        },
        "file_line_tracker": {
            "src/main.py": [1, 2, 3],
            "tests/test_main.py": [10, 11]
        }
    }

    now_ms = int(datetime.now().timestamp() * 1000)

    cursor.execute(
        "INSERT INTO conversations_v2 (key, conversation_id, value, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("/workspace/project_v2", "test-v2-uuid-1", json.dumps(v2_value), now_ms, now_ms)
    )

    # Insert legacy conversation
    v1_value = {
        "transcript": [
            "> hello",
            "world"
        ],
        "history": [
            {
                "user": {"content": {"Prompt": {"prompt": "hello"}}},
                "assistant": {"ToolUse": {"content": "world"}}
            }
        ],
        "latest_summary": "Legacy session summary",
        "model_info": {
            "model_id": "openai.gpt-4"
        },
        "file_line_tracker": {
            "legacy.py": [1]
        }
    }

    cursor.execute(
        "INSERT INTO conversations (key, value) VALUES (?, ?)",
        ("/workspace/project_v1", json.dumps(v1_value))
    )

    conn.commit()
    conn.close()

    yield

    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)


def test_get_sessions():
    sessions = kiro_sessionizer.get_sessions()
    assert len(sessions) == 2
    # Sorted by updated_at desc (v2 has now_ms, legacy has 0)
    assert sessions[0]["key"] == "/workspace/project_v2"
    assert sessions[0]["id"] == "test-v2-uuid-1"
    assert sessions[1]["key"] == "/workspace/project_v1"
    assert sessions[1]["id"] == "legacy"


def test_stats_command(capsys):
    kiro_sessionizer.show_stats()
    captured = capsys.readouterr()
    assert "Total Sessions:" in captured.out
    assert "project_v2" in captured.out
    assert "project_v1" in captured.out
    assert "main.py" in captured.out
    assert "legacy.py" in captured.out


def test_commit_draft_command(capsys):
    kiro_sessionizer.draft_commit()
    captured = capsys.readouterr()
    assert "feat(project_v2): implement workflow updates" in captured.out
    assert "Taught python coding basics." in captured.out
    assert "src/main.py" in captured.out
    assert "tests/test_main.py" in captured.out


def test_report_command(capsys):
    # Generates a report for past 30 days
    kiro_sessionizer.generate_report(days=30)
    captured = capsys.readouterr()
    assert "# Daily Standup / Session Report" in captured.out
    assert "[project_v2] Session test-v2-" in captured.out


def test_journal_command(capsys):
    kiro_sessionizer.generate_journal("/workspace/project_v2")
    captured = capsys.readouterr()
    assert "# Project Journal: project_v2" in captured.out
    assert "how to code" in captured.out
    assert "Outcome / Summary:" in captured.out
    assert "Taught python coding basics." in captured.out


@patch("os.path.exists")
@patch("os.path.isdir")
def test_jump_command(mock_isdir, mock_exists, capsys):
    mock_exists.return_value = True
    mock_isdir.return_value = True

    with patch("subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = ("/workspace/project_v2\n", "")
        mock_popen.return_value = mock_process

        kiro_sessionizer.jump_to_project()
        captured = capsys.readouterr()
        assert "cd /workspace/project_v2" in captured.out


@patch("os.path.exists")
@patch("subprocess.run")
@patch("subprocess.call")
def test_restore_command(mock_call, mock_run, mock_exists):
    mock_exists.side_effect = lambda path: True if DB_FILE in path or "project_v2" in path or "main.py" in path or "test_main.py" in path else False
    mock_call.return_value = 0 # simulate code exists

    kiro_sessionizer.restore_session_files("/workspace/project_v2", "test-v2-uuid-1", editor="code")
    mock_run.assert_called_with(["code", "/workspace/project_v2/src/main.py", "/workspace/project_v2/tests/test_main.py"])


def test_prune_command(capsys):
    # Dry run
    kiro_sessionizer.prune_sessions(days=0, min_messages=10, dry_run=True)
    captured = capsys.readouterr()
    assert "*** DRY RUN MODE ***" in captured.err

    # Actual apply with force
    kiro_sessionizer.prune_sessions(days=0, min_messages=10, dry_run=False, force=True)

    # Verify deletions
    sessions = kiro_sessionizer.get_sessions()
    assert len(sessions) == 0
