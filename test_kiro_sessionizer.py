import os
import sys
import json
import sqlite3
import pytest
from unittest.mock import patch

import kiro_sessionizer

# Helper to remove ANSI color codes
def strip_ansi(text):
    import re
    return re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])').sub('', text)

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_data.sqlite3"
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Create tables
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

    conn.commit()
    conn.close()

    # Patch DB_PATH in kiro_sessionizer and mock os.path.exists to return True for our db_file
    orig_exists = os.path.exists
    def mock_exists(path):
        if path == str(db_file):
            return True
        return orig_exists(path)

    with patch("kiro_sessionizer.DB_PATH", str(db_file)), \
         patch("os.path.exists", side_effect=mock_exists):
        yield db_file

def test_generate_journal_no_entries(temp_db, capsys):
    # Test project that has no entries
    kiro_sessionizer.generate_journal("/nonexistent/project")
    captured = capsys.readouterr()
    assert "No journal entries found for project" in captured.out

def test_generate_journal_with_v2_entries(temp_db, capsys):
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()

    abs_project_path = os.path.abspath(".")

    # Add a v2 session
    v2_value = {
        "conversation_id": "session-v2-uuid",
        "latest_summary": "Implemented feature XYZ and updated setup.py.",
        "transcript": [
            "> What features should we add?",
            "Assistant: We should add a project journal.",
            "> Awesome, let's do it."
        ],
        "history": [
            {
                "user": {
                    "content": { "Prompt": { "prompt": "What features should we add?" } }
                }
            }
        ],
        "model_info": {
            "model_id": "anthropic.claude-3-opus"
        }
    }

    cursor.execute(
        "INSERT INTO conversations_v2 (key, conversation_id, value, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (abs_project_path, "session-v2-uuid", json.dumps(v2_value), 1700000000000, 1700000060000)
    )
    conn.commit()
    conn.close()

    kiro_sessionizer.generate_journal(abs_project_path)
    captured = capsys.readouterr()

    plain_output = strip_ansi(captured.out)
    assert "Chronological Developer Journal" in plain_output
    assert "session-v2-uuid" in plain_output
    assert "anthropic.claude-3-opus" in plain_output
    assert "What features should we add?" in plain_output
    assert "Implemented feature XYZ and updated setup.py" in plain_output

def test_generate_journal_with_legacy_and_fallback(temp_db, capsys):
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()

    abs_project_path = os.path.abspath(".")

    # Add a legacy session with fallback outcome (no summary)
    v1_value = {
        "transcript": [
            "> How to fix this bug?",
            "Assistant: Just remove the legacy tables."
        ],
        "history": [],
        "model_info": {
            "model_id": "legacy-model"
        }
    }

    cursor.execute(
        "INSERT INTO conversations (key, value) VALUES (?, ?)",
        (abs_project_path, json.dumps(v1_value))
    )
    conn.commit()
    conn.close()

    kiro_sessionizer.generate_journal(abs_project_path)
    captured = capsys.readouterr()

    plain_output = strip_ansi(captured.out)
    assert "Chronological Developer Journal" in plain_output
    assert "legacy" in plain_output
    assert "How to fix this bug?" in plain_output
    assert "Outcome (Latest): Just remove the legacy tables" in plain_output

def test_generate_journal_missing_db(capsys):
    with patch("kiro_sessionizer.DB_PATH", "/nonexistent/path/data.sqlite3"), \
         patch("os.path.exists", return_value=False):
        kiro_sessionizer.generate_journal(".")
        captured = capsys.readouterr()
        assert "Error: Database not found" in captured.err

def test_generate_journal_missing_tables(temp_db, capsys):
    # Drop table to cause OperationalError
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE conversations_v2")
    cursor.execute("DROP TABLE conversations")
    conn.commit()
    conn.close()

    kiro_sessionizer.generate_journal(".")
    captured = capsys.readouterr()
    assert "No journal entries found" in captured.out
