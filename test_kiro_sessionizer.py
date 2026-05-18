import unittest
import re
from kiro_sessionizer import strip_ansi

class TestKiroSessionizer(unittest.TestCase):
    def test_strip_ansi(self):
        colored_text = "\033[34mProject\033[0m"
        self.assertEqual(strip_ansi(colored_text), "Project")

        bold_cyan = "\033[1m\033[36mModel\033[0m"
        self.assertEqual(strip_ansi(bold_cyan), "Model")

        mixed = "Normal \033[32mGreen\033[0m \033[1mBold\033[0m"
        self.assertEqual(strip_ansi(mixed), "Normal Green Bold")

if __name__ == "__main__":
    unittest.main()
