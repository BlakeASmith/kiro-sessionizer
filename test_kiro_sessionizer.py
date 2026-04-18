import pytest
import os
import sqlite3
import json
import kiro_sessionizer
from datetime import datetime, timedelta

@pytest.fixture
def mock_db(tmp_path):
    db_path = tmp_path / "data.sqlite3"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE conversations_v2 (key TEXT, conversation_id TEXT, value TEXT, updated_at INTEGER, created_at INTEGER)")
    cursor.execute("CREATE TABLE conversations (key TEXT, value TEXT)")

    # Insert some test data
    now = datetime.now()
    today_ms = int(now.timestamp() * 1000)
    yesterday_ms = int((now - timedelta(days=1)).timestamp() * 1000)

    def insert_session(key, conv_id, transcript, updated_at, summary=None):
        data = {
            "transcript": transcript,
            "history": [{} for _ in range(len(transcript))],
            "model_info": {"model_id": "test-model"},
            "latest_summary": summary
        }
        cursor.execute("INSERT INTO conversations_v2 (key, conversation_id, value, updated_at, created_at) VALUES (?, ?, ?, ?, ?)",
                       (key, conv_id, json.dumps(data), updated_at, updated_at))

    insert_session("/path/projectA", "id1", ["> Hello", "Hi"], today_ms, "Summary A")
    insert_session("/path/projectB", "id2", ["> Question"], yesterday_ms)

    conn.commit()
    conn.close()

    os.environ["KIRO_DB_PATH"] = str(db_path)
    return db_path

def test_get_sessions(mock_db):
    sessions = kiro_sessionizer.get_sessions()
    assert len(sessions) == 2
    assert sessions[0]["key"] == "/path/projectA"
    assert sessions[0]["last_user_msg"] == "Hello"
    assert "data" in sessions[0]
    assert sessions[0]["data"]["latest_summary"] == "Summary A"

def test_timeline_output(mock_db, capsys):
    kiro_sessionizer.show_timeline()
    captured = capsys.readouterr()
    assert "--- TODAY ---" in captured.out
    assert "--- YESTERDAY ---" in captured.out
    assert "projectA" in captured.out
    assert "projectB" in captured.out
    assert "Summary A" in captured.out

def test_report_output(mock_db, capsys):
    kiro_sessionizer.show_report()
    captured = capsys.readouterr()
    assert "Daily Accomplishments Report" in captured.out
    assert "projectA" in captured.out
    assert "Summary A" in captured.out
    assert "projectB" not in captured.out # Yesterday's session should not be in today's report

def test_continue_project_filter(mock_db):
    sessions = kiro_sessionizer.get_sessions()

    # Test project filter logic (extracting from main logic)
    def get_selected(project_query):
        query = project_query.lower()
        for s in sessions:
            project = os.path.basename(s["key"]).lower()
            if query in project:
                return s
        return None

    assert get_selected("projectA")["id"] == "id1"
    assert get_selected("projectB")["id"] == "id2"
    assert get_selected("A")["id"] == "id1"
    assert get_selected("nonexistent") is None

def test_strip_ansi():
    text = "\033[34mBlue Text\033[0m"
    assert kiro_sessionizer.strip_ansi(text) == "Blue Text"
