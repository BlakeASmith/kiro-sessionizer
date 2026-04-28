import pytest
from kiro_sessionizer import strip_ansi

def test_strip_ansi():
    assert strip_ansi("\033[34mHello\033[0m") == "Hello"
    assert strip_ansi("\033[1;31mWorld\033[0m") == "World"
    assert strip_ansi("Plain text") == "Plain text"
    assert strip_ansi("\x1B[31mRed\x1B[0m") == "Red"
