import pytest
from kiro_sessionizer import strip_ansi

def test_strip_ansi_empty():
    assert strip_ansi("") == ""

def test_strip_ansi_plain_text():
    assert strip_ansi("hello world") == "hello world"

def test_strip_ansi_simple_color():
    # \033[34m is BLUE
    assert strip_ansi("\033[34mhello\033[0m") == "hello"

def test_strip_ansi_complex():
    # Multiple codes and styles
    text = "\033[1m\033[34mBOLD BLUE\033[0m \033[32mGREEN\033[0m"
    assert strip_ansi(text) == "BOLD BLUE GREEN"

def test_strip_ansi_with_tabs():
    text = "\033[34mProject\033[0m\t\033[33mDate\033[0m"
    assert strip_ansi(text) == "Project\tDate"

def test_strip_ansi_csi_sequences():
    # More complex ANSI CSI sequences
    text = "\x1B[H\x1B[2J\x1B[31mRed\x1B[0m"
    assert strip_ansi(text) == "Red"

def test_strip_ansi_non_csi():
    # ESC followed by other characters in the [@-Z\\-_] range
    text = "\x1BD" # Index (IND)
    assert strip_ansi(text) == ""

    text = "\x1BM" # Reverse Index (RI)
    assert strip_ansi(text) == ""
