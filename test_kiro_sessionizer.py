import unittest
from kiro_sessionizer import strip_ansi
import signal
import os

class TestKiroSessionizer(unittest.TestCase):
    def test_strip_ansi(self):
        text = "\033[34mProject\033[0m"
        self.assertEqual(strip_ansi(text), "Project")

        text2 = "\033[1mBold\033[0m \033[32mGreen\033[0m"
        self.assertEqual(strip_ansi(text2), "Bold Green")

if __name__ == '__main__':
    unittest.main()
