import unittest
from kiro_sessionizer import strip_ansi

class TestKiroSessionizer(unittest.TestCase):
    def test_strip_ansi(self):
        colored_text = "\033[34mProject\033[0m"
        self.assertEqual(strip_ansi(colored_text), "Project")

        complex_text = "\033[1m\033[34mBoldBlue\033[0m\t\033[33mYellow\033[0m"
        self.assertEqual(strip_ansi(complex_text), "BoldBlue\tYellow")

if __name__ == "__main__":
    unittest.main()
