import pytest
import sqlite3
import json
import os
import tempfile
import shutil
from unittest.mock import MagicMock, patch
import kiro_sessionizer

@pytest.fixture
def test_env(monkeypatch):
    # Create temp directory for database and sessions
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_data.sqlite3")
    sessions_dir = os.path.join(temp_dir, "sessions")
    os.makedirs(sessions_dir, exist_ok=True)

    # Overwrite DB_PATH and SESSIONS_DIR in kiro_sessionizer
    monkeypatch.setattr(kiro_sessionizer, "DB_PATH", db_path)
    monkeypatch.setattr(kiro_sessionizer, "SESSIONS_DIR", sessions_dir)

    # Create DB tables
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE conversations_v2 (
        key TEXT,
        conversation_id TEXT,
        value TEXT,
        created_at INTEGER,
        updated_at INTEGER,
        PRIMARY KEY (key, conversation_id)
    );
    """)
    cursor.execute("""
    CREATE TABLE conversations (
        key TEXT,
        value TEXT
    );
    """)
    conn.commit()
    conn.close()

    yield temp_dir, db_path, sessions_dir

    shutil.rmtree(temp_dir)


def add_v2_session(db_path, key, conv_id, prompt, response, summary, model, file_tracker, updated_at_ms):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    value_data = {
        "conversation_id": conv_id,
        "history": [
            {
                "user": {"content": {"Prompt": {"prompt": prompt}}, "timestamp": "2026-04-04T12:00:00Z"},
                "assistant": {"ToolUse": {"message_id": "msg-1", "content": response}}
            }
        ],
        "transcript": [
            f"> {prompt}",
            f"Assistant: {response}"
        ],
        "latest_summary": summary,
        "model_info": {
            "model_id": model
        },
        "file_line_tracker": file_tracker
    }

    cursor.execute(
        "INSERT INTO conversations_v2 (key, conversation_id, value, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (key, conv_id, json.dumps(value_data), updated_at_ms, updated_at_ms)
    )
    conn.commit()
    conn.close()


def add_v1_session(db_path, key, prompt, response, summary, model, file_tracker):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    value_data = {
        "transcript": [
            f"> {prompt}",
            f"Assistant: {response}"
        ],
        "latest_summary": summary,
        "model_info": {
            "model_id": model
        },
        "file_line_tracker": file_tracker
    }

    cursor.execute(
        "INSERT INTO conversations (key, value) VALUES (?, ?)",
        (key, json.dumps(value_data))
    )
    conn.commit()
    conn.close()


def test_get_sessions(test_env):
    temp_dir, db_path, sessions_dir = test_env

    # Add v2 session
    add_v2_session(
        db_path,
        key="/Users/test/project_a",
        conv_id="uuid-1",
        prompt="hello from python",
        response="hi",
        summary="Greeted assistant in Python.",
        model="gpt-4o",
        file_tracker={"kiro_sessionizer.py": [1]},
        updated_at_ms=1600000000000
    )

    # Add v1 session
    add_v1_session(
        db_path,
        key="/Users/test/project_b",
        prompt="legacy chat",
        response="legacy text",
        summary="Legacy chat session.",
        model="claude-3-opus",
        file_tracker={"legacy.py": [1, 2]},
    )

    sessions = kiro_sessionizer.get_sessions()
    assert len(sessions) == 2

    v2_sess = [s for s in sessions if s["source"] == "v2"][0]
    assert v2_sess["key"] == "/Users/test/project_a"
    assert v2_sess["id"] == "uuid-1"

    v1_sess = [s for s in sessions if s["source"] == "v1"][0]
    assert v1_sess["key"] == "/Users/test/project_b"
    assert v1_sess["id"] == "legacy"


def test_show_stats(test_env, capsys):
    temp_dir, db_path, sessions_dir = test_env

    # Add some sessions
    add_v2_session(
        db_path,
        key="/Users/test/project_a",
        conv_id="uuid-1",
        prompt="query",
        response="reply",
        summary="Summary a",
        model="gpt-4o",
        file_tracker={"test_file.py": [1]},
        updated_at_ms=1600000000000
    )

    kiro_sessionizer.show_stats()
    captured = capsys.readouterr().out
    clean_out = kiro_sessionizer.strip_ansi(captured)

    assert "Total Sessions:  1" in clean_out
    assert "project_a" in clean_out
    assert "test_file.py" in clean_out
    assert "gpt-4o" in clean_out


def test_draft_commit_message(test_env, capsys):
    temp_dir, db_path, sessions_dir = test_env

    add_v2_session(
        db_path,
        key="/Users/test/project_a",
        conv_id="uuid-1",
        prompt="Implement jump feature",
        response="Sure",
        summary="Added the jump command for workspace navigation.",
        model="gpt-4o",
        file_tracker={"src/navigation.py": [1, 2]},
        updated_at_ms=int(kiro_sessionizer.datetime.now().timestamp() * 1000)
    )

    kiro_sessionizer.draft_commit_message()
    captured = capsys.readouterr().out
    clean_out = kiro_sessionizer.strip_ansi(captured)

    assert "feat: implement jump feature" in clean_out
    assert "Added the jump command for workspace navigation." in clean_out
    assert "src/navigation.py" in clean_out


def test_generate_standup_report(test_env, capsys):
    temp_dir, db_path, sessions_dir = test_env

    now_ms = int(kiro_sessionizer.datetime.now().timestamp() * 1000)

    add_v2_session(
        db_path,
        key="/Users/test/project_a",
        conv_id="uuid-1",
        prompt="fixing bug",
        response="done",
        summary="Fixed standard session lookup bug.",
        model="gpt-4",
        file_tracker={"bug.py": [1]},
        updated_at_ms=now_ms
    )

    # A session outside of 1-day timeframe
    add_v2_session(
        db_path,
        key="/Users/test/project_b",
        conv_id="uuid-2",
        prompt="old prompt",
        response="old reply",
        summary="Old stuff.",
        model="gpt-4",
        file_tracker={"old.py": [1]},
        updated_at_ms=now_ms - (3 * 24 * 60 * 60 * 1000)
    )

    kiro_sessionizer.generate_standup_report(days=1)
    captured = capsys.readouterr().out
    clean_out = kiro_sessionizer.strip_ansi(captured)

    assert "# Work Session Report (Last 1 Days)" in clean_out
    assert "project_a" in clean_out
    assert "Fixed standard session lookup bug." in clean_out
    assert "bug.py" in clean_out
    assert "project_b" not in clean_out


def test_generate_project_journal(test_env, capsys):
    temp_dir, db_path, sessions_dir = test_env

    now_ms = int(kiro_sessionizer.datetime.now().timestamp() * 1000)
    project_path = os.path.join(temp_dir, "my_project")
    os.makedirs(project_path, exist_ok=True)

    add_v2_session(
        db_path,
        key=project_path,
        conv_id="uuid-1",
        prompt="first task",
        response="ok",
        summary="Journal entry 1 summary.",
        model="gpt-4o",
        file_tracker={"main.py": [1]},
        updated_at_ms=now_ms - 10000
    )

    add_v2_session(
        db_path,
        key=project_path,
        conv_id="uuid-2",
        prompt="second task",
        response="ok2",
        summary="Journal entry 2 summary.",
        model="gpt-4o",
        file_tracker={"main.py": [10]},
        updated_at_ms=now_ms
    )

    kiro_sessionizer.generate_project_journal(project_path)
    captured = capsys.readouterr().out
    clean_out = kiro_sessionizer.strip_ansi(captured)

    assert "Project Development Journal" in clean_out
    assert "Total Sessions: 2" in clean_out
    assert "Entry #1" in clean_out
    assert "Journal entry 1 summary." in clean_out
    assert "Entry #2" in clean_out
    assert "Journal entry 2 summary." in clean_out


def test_prune_sessions(test_env, capsys):
    temp_dir, db_path, sessions_dir = test_env

    now_ms = int(kiro_sessionizer.datetime.now().timestamp() * 1000)

    # Old session to prune
    add_v2_session(
        db_path,
        key="/Users/test/project_old",
        conv_id="uuid-old",
        prompt="very old",
        response="reply",
        summary="Old summary",
        model="gpt-4",
        file_tracker={},
        updated_at_ms=now_ms - (40 * 24 * 60 * 60 * 1000)
    )

    # Recent session to keep
    add_v2_session(
        db_path,
        key="/Users/test/project_new",
        conv_id="uuid-new",
        prompt="very new",
        response="reply",
        summary="New summary",
        model="gpt-4",
        file_tracker={},
        updated_at_ms=now_ms
    )

    # Test dry run mode first
    kiro_sessionizer.prune_sessions(days=30, apply=False)
    captured = capsys.readouterr().out
    assert "*** DRY RUN MODE ***" in captured

    # Assert nothing was deleted in dry-run
    sessions = kiro_sessionizer.get_sessions()
    assert len(sessions) == 2

    # Run with apply=True and force=True
    kiro_sessionizer.prune_sessions(days=30, apply=True, force=True)

    sessions_after = kiro_sessionizer.get_sessions()
    assert len(sessions_after) == 1
    assert sessions_after[0]["id"] == "uuid-new"


def test_jump_to_project(test_env, monkeypatch, capsys):
    temp_dir, db_path, sessions_dir = test_env

    proj_a = os.path.join(temp_dir, "proj_a")
    proj_b = os.path.join(temp_dir, "proj_b")
    os.makedirs(proj_a, exist_ok=True)
    os.makedirs(proj_b, exist_ok=True)

    add_v2_session(
        db_path,
        key=proj_a,
        conv_id="uuid-a",
        prompt="hello",
        response="hi",
        summary="Summary a",
        model="gpt-4",
        file_tracker={},
        updated_at_ms=1600000000000
    )

    # Mock subprocess.Popen for fzf call in jump_to_project
    mock_popen = MagicMock()
    mock_process = MagicMock()
    # Let fzf return the second line selection (proj_a)
    mock_process.communicate.return_value = (f"proj_a\t{proj_a}\n", None)
    mock_process.returncode = 0
    mock_popen.return_value = mock_process

    monkeypatch.setattr(kiro_sessionizer.subprocess, "Popen", mock_popen)

    kiro_sessionizer.jump_to_project()
    captured = capsys.readouterr().out
    assert f"cd {proj_a}" in captured


def test_restore_session_workspace(test_env, monkeypatch, capsys):
    temp_dir, db_path, sessions_dir = test_env

    workspace_path = os.path.join(temp_dir, "workspace")
    os.makedirs(workspace_path, exist_ok=True)

    existing_file_path = os.path.join(workspace_path, "code.py")
    with open(existing_file_path, "w") as f:
        f.write("print('hello')\n")

    add_v2_session(
        db_path,
        key=workspace_path,
        conv_id="uuid-restore",
        prompt="write code",
        response="done",
        summary="Wrote a python script.",
        model="gpt-4",
        file_tracker={"code.py": [1]},
        updated_at_ms=1600000000000
    )

    # Mock subprocess.Popen to avoid actually opening an editor
    mock_popen = MagicMock()
    monkeypatch.setattr(kiro_sessionizer.subprocess, "Popen", mock_popen)

    # Test restore
    kiro_sessionizer.restore_session_workspace("uuid-restore", path=workspace_path, editor="nano")

    mock_popen.assert_called_once_with(["nano", existing_file_path], stdout=kiro_sessionizer.subprocess.DEVNULL, stderr=kiro_sessionizer.subprocess.DEVNULL)
    captured = capsys.readouterr().err
    assert "Opening 1 file(s) in nano" in captured
