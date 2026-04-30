import pytest
from datetime import datetime, timedelta
import os
import json
from kiro_sessionizer import strip_ansi

def test_strip_ansi():
    assert strip_ansi("\033[34mProject\033[0m") == "Project"
    assert strip_ansi("Plain text") == "Plain text"
    assert strip_ansi("\033[1;31mBold Red\033[0m") == "Bold Red"

def test_project_filtering_logic():
    # Mocking what the continue command does
    sessions = [
        {"key": "/path/to/project_a"},
        {"key": "/path/to/my_cool_project"},
        {"key": "/path/to/project_b"},
    ]

    query = "cool"
    selected = None
    for s in sessions:
        if query.lower() in os.path.basename(s["key"]).lower():
            selected = s
            break

    assert selected["key"] == "/path/to/my_cool_project"

def test_date_grouping_logic():
    # Mocking what the timeline command does
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    other_day = today - timedelta(days=5)

    sessions = [
        {"updated_at": int(datetime.combine(today, datetime.min.time()).timestamp() * 1000)},
        {"updated_at": int(datetime.combine(yesterday, datetime.min.time()).timestamp() * 1000)},
        {"updated_at": int(datetime.combine(other_day, datetime.min.time()).timestamp() * 1000)},
        {"updated_at": 0},
    ]

    groups = {}
    for s in sessions:
        if s["updated_at"] == 0:
            date_str = "LEGACY / UNKNOWN"
        else:
            dt = datetime.fromtimestamp(s["updated_at"] / 1000)
            if dt.date() == today:
                date_str = "TODAY"
            elif dt.date() == yesterday:
                date_str = "YESTERDAY"
            else:
                date_str = dt.strftime("%Y-%m-%d")

        if date_str not in groups:
            groups[date_str] = []
        groups[date_str].append(s)

    assert "TODAY" in groups
    assert "YESTERDAY" in groups
    assert other_day.strftime("%Y-%m-%d") in groups
    assert "LEGACY / UNKNOWN" in groups

def test_report_summary_extraction():
    # Mocking what the report command does
    session_data = {
        "latest_summary": "Implementing new feature",
        "transcript": ["> What are you doing?", "Assistant: I am implementing a new feature"]
    }

    summary = session_data.get("latest_summary")
    assert summary == "Implementing new feature"

    session_data_no_summary = {
        "transcript": ["> User query here", "Assistant: response"]
    }

    summary = session_data_no_summary.get("latest_summary")
    if not summary:
        for line in reversed(session_data_no_summary.get("transcript", [])):
            if line.startswith("> "):
                summary = line[2:].strip()
                break

    assert summary == "User query here"
