import pytest
from datetime import datetime, timedelta
from kiro_sessionizer import strip_ansi, show_timeline

def test_strip_ansi():
    assert strip_ansi("\033[34mProject\033[0m") == "Project"
    assert strip_ansi("\033[1m\033[32m●\033[0m") == "●"
    assert strip_ansi("Plain Text") == "Plain Text"
    assert strip_ansi("\033[31;1mComplex\033[0m") == "Complex"

def test_show_timeline_grouping():
    now_ms = int(datetime.now().timestamp() * 1000)
    yesterday_ms = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)
    older_ms = int((datetime.now() - timedelta(days=5)).timestamp() * 1000)

    sessions = [
        {"updated_at": now_ms, "display": "session1", "key": "/p1", "id": "1"},
        {"updated_at": yesterday_ms, "display": "session2", "key": "/p2", "id": "2"},
        {"updated_at": older_ms, "display": "session3", "key": "/p3", "id": "3"},
        {"updated_at": 0, "display": "session4", "key": "/p4", "id": "4"},
    ]

    timeline = show_timeline(sessions)

    # Check for headers
    headers = [s["display"] for s in timeline if s.get("is_header")]
    assert any("TODAY" in h for h in headers)
    assert any("YESTERDAY" in h for h in headers)
    assert any("LEGACY" in h for h in headers)

    # Check order
    # Header TODAY
    # session1
    # Header YESTERDAY
    # session2
    # ...

    assert "session1" in [s.get("display") for s in timeline]

def test_show_timeline_empty():
    assert show_timeline([]) == []
