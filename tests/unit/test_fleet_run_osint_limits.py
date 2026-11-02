"""RF1510-8: ``run_osint.py`` refuses out-of-range batch limits (exit 2); ``run`` is patched, no session starts."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import os
import unittest
from unittest import mock

from tests._support import ROOT

_spec = importlib.util.spec_from_file_location("run_osint_limits", ROOT / "scripts/fleet/run_osint.py")
run_osint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_osint)

RUN_ID = "20261011T101700Z-abcdef"
MINUTES = "must be minutes above 0 and at most 360"
ENV_ERROR = "FLEET_OSINT_PARALLEL must be a whole number from 1 to 8"


class LimitTests(unittest.TestCase):
    def main(self, *extra, env=None, base=("--region", "CA", "--run-id", RUN_ID)):
        """Run ``main`` with ``run`` patched; returns (exit code, stdout, stderr, the run mock)."""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(run_osint, "run", return_value=(0, {"done": 0})) as run, \
                mock.patch.dict(os.environ, env or {}, clear=True), redirect_stdout(out), redirect_stderr(err):
            try:
                code = run_osint.main([*base, *extra])
            except SystemExit as exit_:
                code = exit_.code
        return code, out.getvalue(), err.getvalue(), run

    def assert_refused(self, flag, value, message, env=None):
        args = () if flag is None else (f"{flag}={value}",)
        code, out, err, run = self.main(*args, env=env)
        self.assertEqual(code, 2)
        self.assertIn(message, err)
        if flag is not None:
            self.assertIn(f"argument {flag}:", err, "stderr names the flag")
        run.assert_not_called()
        self.assertEqual(out, "")
        return err

    def test_minutes_out_of_range_or_not_finite_are_refused(self):
        for flag, value in (("--timeout-min", "0"), ("--timeout-min", "-1"), ("--timeout-min", "nan"),
                            ("--timeout-min", "inf"), ("--timeout-min", "361"), ("--timeout-min", "-inf"),
                            ("--deadline-min", "inf"), ("--deadline-min", "0"), ("--deadline-min", "nan"),
                            ("--deadline-min", "360.01")):
            with self.subTest(flag=flag, value=value):
                self.assert_refused(flag, value, MINUTES)

    def test_counts_out_of_range_are_refused(self):
        for flag, value, message in (("--max-turns", "0", "from 1 to 1000"), ("--max-turns", "-5", "from 1 to 1000"),
                                     ("--max-turns", "1001", "from 1 to 1000"),
                                     ("--parallel", "0", "from 1 to 8"), ("--parallel", "9", "from 1 to 8"),
                                     ("--parallel", "-1", "from 1 to 8")):
            with self.subTest(flag=flag, value=value):
                self.assert_refused(flag, value, f"must be a whole number {message}")

    def test_parallel_zero_is_not_replaced_by_the_environment(self):
        self.assert_refused("--parallel", "0", "from 1 to 8", env={"FLEET_OSINT_PARALLEL": "4"})

    def test_separate_word_values_are_refused_too(self):
        for args, message in ((("--timeout-min", "-1"), MINUTES), (("--deadline-min", "inf"), MINUTES),
                              (("--max-turns", "-5"), "from 1 to 1000"), (("--parallel", "0"), "from 1 to 8")):
            with self.subTest(args=args):
                code, _out, err, run = self.main(*args)
                self.assertEqual(code, 2)
                self.assertIn(f"argument {args[0]}: ", err)
                self.assertIn(message, err)
                run.assert_not_called()

    def test_bad_environment_parallel_is_refused_without_echoing_it(self):
        for value in ("abc", "0", "12", "2.5", "-3"):
            with self.subTest(value=value):
                err = self.assert_refused(None, None, ENV_ERROR, env={"FLEET_OSINT_PARALLEL": value})
                self.assertNotIn(value, err.replace(ENV_ERROR, ""), "the value is not printed")

    def test_the_flag_wins_over_a_bad_environment_value(self):
        code, _out, _err, run = self.main("--parallel", "2", env={"FLEET_OSINT_PARALLEL": "abc"})
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args.kwargs["parallel"], 2)

    def test_boundaries_are_accepted_and_passed_to_run(self):
        for extra, expected in ((("--timeout-min", "0.5"), {"timeout_min": 0.5}),
                                (("--timeout-min", "360"), {"timeout_min": 360.0}),
                                (("--deadline-min", "360"), {"deadline_min": 360.0}),
                                (("--deadline-min", "0.5"), {"deadline_min": 0.5}),
                                (("--max-turns", "1"), {"max_turns": 1}),
                                (("--max-turns", "1000"), {"max_turns": 1000}),
                                (("--parallel", "1"), {"parallel": 1}),
                                (("--parallel", "8"), {"parallel": 8})):
            with self.subTest(extra=extra):
                code, _out, err, run = self.main(*extra)
                self.assertEqual((code, err), (0, ""))
                run.assert_called_once()
                for key, value in expected.items():
                    self.assertEqual(run.call_args.kwargs[key], value)

    def test_parallel_comes_from_the_environment_when_the_flag_is_absent(self):
        for env, expected in (({"FLEET_OSINT_PARALLEL": "8"}, 8), ({"FLEET_OSINT_PARALLEL": "1"}, 1),
                              ({}, run_osint.DEFAULT_PARALLEL), ({"FLEET_OSINT_PARALLEL": ""}, run_osint.DEFAULT_PARALLEL)):
            with self.subTest(env=env):
                code, _out, _err, run = self.main(env=env)
                self.assertEqual(code, 0)
                self.assertEqual(run.call_args.kwargs["parallel"], expected)

    def test_defaults_still_pass(self):
        code, _out, _err, run = self.main()
        self.assertEqual(code, 0)
        kwargs = run.call_args.kwargs
        self.assertEqual((kwargs["timeout_min"], kwargs["max_turns"], kwargs["deadline_min"]),
                         (run_osint.DEFAULT_TIMEOUT_MIN, run_osint.DEFAULT_MAX_TURNS, run_osint.DEFAULT_DEADLINE_MIN))

    def test_print_cli_version_still_needs_no_region_or_run_id(self):
        code, out, err, run = self.main("--print-cli-version", base=(), env={"FLEET_OSINT_PARALLEL": "abc"})
        self.assertEqual((code, out.strip(), err), (0, run_osint.CLAUDE_CODE_VERSION, ""))
        run.assert_not_called()

    def test_missing_region_is_reported_before_the_environment_check(self):
        code, _out, err, run = self.main(base=("--region", "CA"), env={"FLEET_OSINT_PARALLEL": "abc"})
        self.assertEqual(code, 2)
        self.assertIn("--region and --run-id are required", err)
        self.assertNotIn("FLEET_OSINT_PARALLEL", err)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
