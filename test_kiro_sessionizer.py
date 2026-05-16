import unittest
import kiro_sessionizer
import os

class TestKiroSessionizer(unittest.TestCase):
    def test_strip_ansi(self):
        colored_text = "\033[34mHello\033[0m"
        self.assertEqual(kiro_sessionizer.strip_ansi(colored_text), "Hello")

    def test_strip_ansi_no_color(self):
        text = "Hello"
        self.assertEqual(kiro_sessionizer.strip_ansi(text), "Hello")

if __name__ == "__main__":
    unittest.main()
