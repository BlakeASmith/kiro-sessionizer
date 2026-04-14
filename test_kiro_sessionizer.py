import pytest
import sqlite3
import json
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import kiro_sessionizer

@pytest.fixture
def mock_db():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE conversations_v2 (
            key TEXT,
            conversation_id TEXT,
            value TEXT,
            created_at INTEGER,
            updated_at INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE conversations (
            key TEXT,
            value TEXT
        )
    """)

    # Add some mock data
    now_ms = int(datetime.now().timestamp() * 1000)

    # Session 1: Today
    val1 = json.dumps({
        "transcript": ["> User: Hello", "Assistant: Hi there"],
        "history": [{"user": "Hello"}, {"assistant": "Hi there"}],
        "model_info": {"model_id": "gpt-4"},
        "latest_summary": "Initial greeting"
    })
    cursor.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
                   ("/path/to/project_a", "conv_1", val1, now_ms, now_ms))

    # Session 2: Yesterday
    yesterday_ms = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)
    val2 = json.dumps({
        "transcript": ["> User: Fix bug", "Assistant: OK"],
        "history": [{"user": "Fix bug"}, {"assistant": "OK"}],
        "model_info": {"model_id": "claude-3"},
        "latest_summary": "Bug fixing"
    })
    cursor.execute("INSERT INTO conversations_v2 VALUES (?, ?, ?, ?, ?)",
                   ("/path/to/project_b", "conv_2", val2, yesterday_ms, yesterday_ms))

    # Session 3: Legacy
    val3 = json.dumps({
        "transcript": ["> User: Old stuff", "Assistant: Right"],
        "history": [{"user": "Old stuff"}, {"assistant": "Right"}],
        "model_info": {"model_id": "gpt-3.5"}
    })
    cursor.execute("INSERT INTO conversations VALUES (?, ?)",
                   ("/path/to/legacy_project", val3))

    conn.commit()
    conn.close()

    with patch("kiro_sessionizer.DB_PATH", path):
        yield path

    os.remove(path)

@pytest.fixture
def mock_sessions_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("kiro_sessionizer.SESSIONS_DIR", tmpdir):
            yield tmpdir

def test_get_sessions(mock_db, mock_sessions_dir):
    with patch("kiro_sessionizer.get_active_sessions", return_value={}):
        sessions = kiro_sessionizer.get_sessions()
        assert len(sessions) == 3
        # Sorted by updated_at DESC, so conv_1 should be first
        assert sessions[0]["id"] == "conv_1"
        assert sessions[1]["id"] == "conv_2"
        assert sessions[2]["id"] == "legacy"

def test_strip_ansi():
    text = "\033[34mHello\033[0m"
    assert kiro_sessionizer.strip_ansi(text) == "Hello"

def test_stats(mock_db, capsys):
    with patch("kiro_sessionizer.get_active_sessions", return_value={}):
        kiro_sessionizer.show_stats()
        captured = capsys.readouterr()
        out = kiro_sessionizer.strip_ansi(captured.out)
        assert "Total Sessions:  3" in out
        assert "project_a" in out
        assert "project_b" in out
        assert "gpt-4" in out

def test_search_sessions(mock_db):
    with patch("kiro_sessionizer.get_active_sessions", return_value={}):
        results = kiro_sessionizer.search_sessions("greeting")
        assert len(results) == 1
        assert results[0]["id"] == "conv_1"
        assert "Initial greeting" in results[0]["display"]

def test_delete_sessions(mock_db, mock_sessions_dir):
    # Create dummy files for conv_1
    json_path = os.path.join(mock_sessions_dir, "conv_1.json")
    lock_path = os.path.join(mock_sessions_dir, "conv_1.lock")
    with open(json_path, "w") as f: f.write("{}")
    with open(lock_path, "w") as f: f.write("{}")

    kiro_sessionizer.delete_sessions([("conv_1", "/path/to/project_a")])

    # Check DB
    conn = sqlite3.connect(mock_db)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversations_v2 WHERE conversation_id = 'conv_1'")
    assert cursor.fetchone() is None
    conn.close()

    # Check files
    assert not os.path.exists(json_path)
    assert not os.path.exists(lock_path)

def test_timeline(mock_db, capsys):
    with patch("kiro_sessionizer.get_active_sessions", return_value={}):
        kiro_sessionizer.show_timeline()
        captured = capsys.readouterr()
        out = kiro_sessionizer.strip_ansi(captured.out)
        assert "--- Kiro Session Timeline ---" in out
        assert "TODAY" in out
        assert "YESTERDAY" in out
        assert "project_a" in out
        assert "project_b" in out

def test_report(mock_db, capsys):
    with patch("kiro_sessionizer.get_active_sessions", return_value={}):
        kiro_sessionizer.generate_report()
        captured = capsys.readouterr()
        out = kiro_sessionizer.strip_ansi(captured.out)
        assert "--- Kiro Daily Accomplishments Report" in out
        assert "project_a" in out
        assert "Initial greeting" in out
        # project_b is from yesterday, so it shouldn't be in the report
        assert "project_b" not in out

def test_continue_project(mock_db, capsys):
    with patch("kiro_sessionizer.get_active_sessions", return_value={}):
        # Mock main args
        with patch("sys.argv", ["kiro_sessionizer", "continue", "--project", "project_b"]):
            kiro_sessionizer.main()
            captured = capsys.readouterr()
            # It should output the cd command
            assert "cd /path/to/project_b && kiro-cli chat --resume" in captured.out
