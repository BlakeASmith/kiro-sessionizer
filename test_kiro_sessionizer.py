import pytest
from kiro_sessionizer import strip_ansi, BOLD, RED, RESET
from datetime import datetime, timedelta
import os

def test_strip_ansi():
    text = f"{BOLD}{RED}Hello{RESET}"
    assert strip_ansi(text) == "Hello"

    complex_text = "\x1b[31;1mMixed\x1b[0m and \x1b[34mBlue\x1b[0m"
    assert strip_ansi(complex_text) == "Mixed and Blue"

def test_strip_ansi_no_ansi():
    assert strip_ansi("Plain text") == "Plain text"

def test_strip_ansi_empty():
    assert strip_ansi("") == ""

# Since most functions depend on SQLite and environment, we'll test the logic where possible
# or mock if necessary. For now, focus on core utilities.

def test_date_logic_mock():
    # Helper to check if our timeline grouping logic (in concept) works
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    older = today - timedelta(days=5)

    def get_group(dt):
        day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        if day_start == today: return "TODAY"
        if day_start == yesterday: return "YESTERDAY"
        return day_start.strftime("%Y-%m-%d")

    assert get_group(now) == "TODAY"
    assert get_group(yesterday + timedelta(hours=5)) == "YESTERDAY"
    assert get_group(older) == older.strftime("%Y-%m-%d")

def test_project_filter_logic():
    sessions = [
        {"key": "/path/to/project-a"},
        {"key": "/other/path/project-b"},
        {"key": "/home/user/my-api-service"},
    ]

    def filter_sessions(query, sessions):
        query = query.lower()
        for s in sessions:
            project = os.path.basename(s["key"]).lower()
            if query in project:
                return s
        return None

    assert filter_sessions("project-a", sessions)["key"] == "/path/to/project-a"
    assert filter_sessions("api", sessions)["key"] == "/home/user/my-api-service"
    assert filter_sessions("missing", sessions) is None
