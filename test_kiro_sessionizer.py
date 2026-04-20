import pytest
from unittest.mock import patch, MagicMock
from kiro_sessionizer import strip_ansi, show_timeline, generate_report, get_sessions
import json
import os
from datetime import datetime, timedelta

def test_strip_ansi():
    assert strip_ansi("\033[31mRed\033[0mText") == "RedText"
    assert strip_ansi("Normal Text") == "Normal Text"

@patch('kiro_sessionizer.get_sessions')
def test_show_timeline_empty(mock_get_sessions, capsys):
    mock_get_sessions.return_value = []
    show_timeline()
    captured = capsys.readouterr()
    assert "No sessions found." in captured.out

@patch('kiro_sessionizer.get_sessions')
def test_generate_report_empty(mock_get_sessions, capsys):
    mock_get_sessions.return_value = []
    generate_report()
    captured = capsys.readouterr()
    assert "No sessions found." in captured.out

@patch('kiro_sessionizer.get_sessions')
@patch('kiro_sessionizer.datetime')
def test_timeline_date_grouping(mock_datetime, mock_get_sessions, capsys):
    fixed_now = datetime(2023, 10, 27, 12, 0, 0)
    mock_datetime.now.return_value = fixed_now
    mock_datetime.fromtimestamp.side_with = datetime.fromtimestamp # Can't easily mock fromtimestamp while keeping functionality

    # Simpler approach: Mock only what's needed
    today_ms = int(fixed_now.timestamp() * 1000)
    yesterday_ms = int((fixed_now - timedelta(days=1)).timestamp() * 1000)

    mock_get_sessions.return_value = [
        {"key": "/path/to/today", "updated_at": today_ms, "data": {"latest_summary": "Today Work"}},
        {"key": "/path/to/yesterday", "updated_at": yesterday_ms, "data": {"latest_summary": "Yesterday Work"}},
        {"key": "/path/to/legacy", "updated_at": 0, "data": {"transcript": ["> Query", "Response"]}}
    ]

    # We need to handle the datetime.now().date() in show_timeline
    with patch('kiro_sessionizer.datetime') as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromtimestamp = datetime.fromtimestamp

        show_timeline()
        captured = capsys.readouterr()
        assert "--- TODAY ---" in captured.out
        assert "--- YESTERDAY ---" in captured.out
        assert "--- LEGACY / UNKNOWN ---" in captured.out
        assert "today" in captured.out
        assert "yesterday" in captured.out
        assert "legacy" in captured.out

@patch('kiro_sessionizer.get_sessions')
def test_generate_report_content(mock_get_sessions, capsys):
    now = datetime.now()
    today_ms = int(now.timestamp() * 1000)

    mock_get_sessions.return_value = [
        {
            "key": "/path/to/projectA",
            "updated_at": today_ms,
            "data": {"latest_summary": "Summary A"}
        },
        {
            "key": "/path/to/projectB",
            "updated_at": today_ms,
            "data": {"transcript": ["> Message B", "Reply"]}
        }
    ]

    generate_report()
    captured = capsys.readouterr()
    assert "Daily Activity Report" in captured.out
    assert "[projectA]" in captured.out
    assert "• Summary A" in captured.out
    assert "[projectB]" in captured.out
    assert "• Message B" in captured.out
