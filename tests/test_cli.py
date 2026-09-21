"""Check that users can discover the arguments of the actual subcommands."""

from contextlib import redirect_stdout
from io import StringIO
import unittest

from skippercast.__main__ import main


class CommandHelp(unittest.TestCase):
    def test_subcommand_help_reaches_its_parser(self):
        for command, flag in (("collect", "--config"), ("atlas", "--data")):
            with self.subTest(command=command):
                stream = StringIO()
                with redirect_stdout(stream), self.assertRaises(SystemExit) as raised:
                    main([command, "--help"])
                self.assertEqual(raised.exception.code, 0)
                self.assertIn(flag, stream.getvalue())


if __name__ == "__main__":
    unittest.main()
