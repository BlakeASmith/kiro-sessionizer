import pytest
from kiro_sessionizer import strip_ansi, GREEN, RESET
import os
import json

def test_strip_ansi():
    text = f"{GREEN}Hello{RESET}"
    assert strip_ansi(text) == "Hello"

def test_strip_ansi_no_colors():
    assert strip_ansi("Plain Text") == "Plain Text"

def test_strip_ansi_complex():
    complex_ansi = "\x1B[1;34mBold Blue\x1B[0m and \x1B[32mGreen\x1B[0m"
    assert strip_ansi(complex_ansi) == "Bold Blue and Green"

from unittest.mock import MagicMock, patch
from kiro_sessionizer import get_sessions, show_timeline, generate_report

def test_timeline_grouping(capsys):
    # Mock sessions
    mock_sessions = [
        {
            "key": "/path/project_a",
            "updated_at": int(os.path.getmtime(__file__) * 1000), # Today
            "data": {"latest_summary": "Today's work"},
            "last_user_msg": "Last msg"
        },
        {
            "key": "/path/project_b",
            "updated_at": int((os.path.getmtime(__file__) - 86400) * 1000), # Yesterday
            "data": {},
            "last_user_msg": "Fix bug"
        }
    ]

    with patch('kiro_sessionizer.get_sessions', return_value=mock_sessions):
        show_timeline()
        captured = capsys.readouterr()
        clean_out = strip_ansi(captured.out)
        assert "== TODAY ==" in clean_out
        assert "project_a: Today's work" in clean_out
        assert "== YESTERDAY ==" in clean_out
        assert "project_b: Fix bug" in clean_out

def test_report_content(capsys):
    today_ms = int(os.path.getmtime(__file__) * 1000)
    mock_sessions = [
        {
            "key": "/path/project_a",
            "updated_at": today_ms,
            "data": {"latest_summary": "Summary A"},
            "last_user_msg": "User A"
        }
    ]

    with patch('kiro_sessionizer.get_sessions', return_value=mock_sessions):
        generate_report()
        captured = capsys.readouterr()
        clean_out = strip_ansi(captured.out)
        assert "Daily Activity Report" in clean_out
        assert "# project_a" in clean_out
        assert "- Summary A" in clean_out

def test_new_session_logic():
    with patch('subprocess.run') as mock_run, \
         patch('subprocess.Popen') as mock_popen, \
         patch('kiro_sessionizer.is_fzf_tmux_supported', return_value=False):

        # Mock kiro-cli agent list
        mock_run.return_value = MagicMock(returncode=0, stdout="agent1\nagent2")

        # Mock fzf selection
        mock_fzf = MagicMock()
        mock_fzf.communicate.return_value = ("agent1\n", None)
        mock_fzf.returncode = 0
        mock_popen.return_value = mock_fzf

        from kiro_sessionizer import start_new_session
        import sys
        from io import StringIO

        out = StringIO()
        with patch('sys.stdout', out):
            start_new_session()

        assert "kiro-cli chat --agent agent1" in out.getvalue()
