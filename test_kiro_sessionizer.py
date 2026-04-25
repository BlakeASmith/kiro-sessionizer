import unittest
from kiro_sessionizer import strip_ansi, ANSI_ESCAPE
import re

class TestKiroSessionizer(unittest.TestCase):
    def test_strip_ansi(self):
        colored_text = "\033[34mProject\033[0m"
        self.assertEqual(strip_ansi(colored_text), "Project")

        bold_text = "\033[1mBold\033[0m"
        self.assertEqual(strip_ansi(bold_text), "Bold")

        mixed_text = "\033[34mBlue\t\033[32mGreen\033[0m"
        self.assertEqual(strip_ansi(mixed_text), "Blue\tGreen")

    def test_ansi_escape_regex(self):
        self.assertTrue(ANSI_ESCAPE.search("\033[31mRed\033[0m"))
        self.assertFalse(ANSI_ESCAPE.search("No Color"))

if __name__ == "__main__":
    unittest.main()
