import pytest
from kiro_sessionizer import strip_ansi, show_timeline, get_sessions
from unittest.mock import patch, MagicMock
from datetime import datetime

def test_strip_ansi():
    assert strip_ansi("\033[31mRed Text\033[0m") == "Red Text"
    assert strip_ansi("Plain Text") == "Plain Text"
    assert strip_ansi("\x1B[1;32mBold Green\x1B[0m") == "Bold Green"

@patch("kiro_sessionizer.get_sessions")
@patch("kiro_sessionizer.select_session")
def test_show_timeline_groups(mock_select, mock_get):
    mock_select.return_value = None
    # Mock some sessions
    now = datetime.now().timestamp() * 1000
    yesterday = (datetime.now().timestamp() - 86400) * 1000
    older = (datetime.now().timestamp() - 86400 * 5) * 1000

    mock_get.return_value = [
        {"key": "/tmp/today", "updated_at": now, "display": "today"},
        {"key": "/tmp/yesterday", "updated_at": yesterday, "display": "yesterday"},
        {"key": "/tmp/older", "updated_at": older, "display": "older"},
        {"key": "/tmp/legacy", "updated_at": 0, "display": "legacy"}
    ]

    show_timeline()

    # Check that select_session was called with headers
    called_entries = mock_select.call_args[0][0]
    headers = [e["display"] for e in called_entries if e.get("is_header")]

    assert any("TODAY" in h for h in headers)
    assert any("YESTERDAY" in h for h in headers)
    assert any("LEGACY" in h for h in headers)

def test_get_sessions_database_not_found():
    with patch("os.path.exists", return_value=False):
        with pytest.raises(SystemExit):
            get_sessions()
