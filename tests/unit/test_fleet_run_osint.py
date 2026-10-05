"""The headless OSINT runner, its workflow and the charter-osint agent contract (design section 8, CF-21).

The runner is driven against a fake ``claude`` executable written into a temporary
directory: it answers ``--version`` and ``auth status``, reads the prompt from stdin,
logs each call (argument list, working directory, environment names) next to itself and
writes empty profiles for the manifest's boats, or fails, hangs or writes nothing as the
test's plan says. Manifests come from ``agent.manifests`` over invented vessels; nothing
here reaches the network or a real CLI.
"""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from skippercast.fleet import agent
from tests._support import ROOT

_spec = importlib.util.spec_from_file_location("run_osint", ROOT / "scripts/fleet/run_osint.py")
run_osint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_osint)

RUN_ID = "20261011T101700Z-abcdef"
AGENT_MD = ROOT / ".claude/agents/charter-osint.md"
WORKFLOW = ROOT / ".github/workflows/fleet-osint.yml"
RUNBOOK = ROOT / "docs/operations/runbooks/fleet-osint.md"
HOSTS = [h["host"] for h in json.loads((ROOT / "catalog/fleet/off-limits.json").read_text())["hosts"]]

FAKE = r'''#!{python}
import json, os, re, sys, time
from pathlib import Path
here = Path(os.path.abspath(sys.argv[0])).parent
args = sys.argv[1:]
if args == ["--version"]:
    print((here / "version").read_text().strip() if (here / "version").exists() else "{version} (Claude Code)")
    sys.exit(0)
if args[:2] == ["auth", "status"]:
    auth = {{"loggedIn": True, "authMethod": "oauth_token", "apiProvider": "firstParty"}}
    if (here / "auth.json").exists():
        auth = json.loads((here / "auth.json").read_text())
    print(json.dumps(auth))
    sys.exit(0)
prompt = sys.stdin.read()
manifest = Path(re.search(r"batch manifest (\S+\.json)", prompt).group(1))
doc = json.loads(manifest.read_text())
batch = doc["batch_id"]
plan = json.loads((here / "plan.json").read_text()) if (here / "plan.json").exists() else {{}}
behaviour = plan.get(batch, "ok")
log = here / "calls.jsonl"
before = sum(1 for line in log.read_text().splitlines() if json.loads(line)["batch"] == batch) if log.exists() else 0
with log.open("a") as f:
    f.write(json.dumps({{"batch": batch, "argv": args, "cwd": os.getcwd(), "env": sorted(os.environ),
                        "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"), "prompt": prompt,
                        "config_dir": os.environ.get("CLAUDE_CONFIG_DIR"), "pid": os.getpid(),
                        "start": time.monotonic()}}) + "\n")
time.sleep(float(plan.get("_sleep", 0)))
if behaviour == "hang-tree":
    import subprocess
    # A tool's child that ignores SIGTERM; it records itself once the handler is in place.
    subprocess.Popen([sys.executable, "-c", "import os, signal, sys, time; signal.signal(signal.SIGTERM, "
                      "signal.SIG_IGN); open(sys.argv[1], 'a').write(str(os.getpid()) + '\\n'); time.sleep(60)",
                      str(here / "children.txt")])
    time.sleep(60)
if behaviour == "hang":
    time.sleep(60)
if behaviour == "fail" or (behaviour == "fail-once" and before == 0):
    print(json.dumps({{"type": "result", "subtype": "error_during_execution", "is_error": True}}))
    sys.exit(1)
if behaviour == "error-result":
    print(json.dumps({{"type": "result", "subtype": "error_max_turns", "is_error": True, "num_turns": 200}}))
    sys.exit(0)
if behaviour != "no-profiles":
    for boat in doc["boats"]:
        Path(doc["output_dir"], boat["vessel_id"] + ".json").write_text("{{}}")
with (here / "ends.jsonl").open("a") as f:
    f.write(json.dumps({{"batch": batch, "end": time.monotonic()}}) + "\n")
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "num_turns": 7, "result": "done",
                  "permission_denials": []}}))
'''


def _alive(pid):
    """A process that exists and is not a zombie (an orphan's parent may not have reaped it yet)."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    except OSError:  # no /proc (macOS): existence only
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
    return state not in ("Z", "X")


def vessel(i):
    return {"id": f"{i:032x}", "name": f"Test Boat {i}", "status": "active", "port_id": "morro-bay", "landing_id": None,
            "vessel_class": "six-pack", "aliases": [], "offerings": [], "last_profiled_at": None}


class Harness:
    """A fleet var with one planned run, a fake claude and the runner's environment."""

    def __init__(self, tmp, boats=5, batch_size=2):
        self.tmp = Path(tmp)
        self.var = self.tmp / "var"
        self.run_dir = self.var / "CA" / "runs" / RUN_ID
        (self.run_dir / "manifests").mkdir(parents=True)
        (self.run_dir / "profiles").mkdir()
        chosen = [(vessel(i), ["new"]) for i in range(1, boats + 1)]
        self.docs = agent.manifests("CA", RUN_ID, self.run_dir, "2026-10-11T10:17:00Z", chosen, batch_size)
        for doc in self.docs:
            (self.run_dir / "manifests" / f"{doc['batch_id']}.json").write_text(json.dumps(doc))
        (self.run_dir / "agent-plan.json").write_text("{}")
        (self.run_dir / "state.json").write_text(json.dumps({"run_id": RUN_ID, "steps": {"plan-agent": {"status": "done"}}}))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.claude = self.bin / "claude"
        self.claude.write_text(FAKE.format(python=sys.executable, version=run_osint.CLAUDE_CODE_VERSION))
        self.claude.chmod(0o755)
        self.environ = {"PATH": f"{self.bin}:{os.environ.get('PATH', '/usr/bin:/bin')}", "HOME": str(self.tmp),
                        "SKIPPERCAST_FLEET_VAR": str(self.var), "CLAUDE_CODE_OAUTH_TOKEN": "test-token-not-real",
                        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "oidc-request", "ACTIONS_ID_TOKEN_REQUEST_URL": "https://oidc.example/",
                        "GITHUB_TOKEN": "gh-token", "GOOGLE_PLACES_API_KEY": "places"}

    def plan(self, **behaviour):
        (self.bin / "plan.json").write_text(json.dumps(behaviour))

    def run(self, **options):
        options.setdefault("parallel", 2)
        return run_osint.run("CA", RUN_ID, claude=str(self.claude), environ=self.environ,
                             auth_file=self.tmp / "missing.env", **options)

    def calls(self, batch=None):
        log = self.bin / "calls.jsonl"
        rows = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return [r for r in rows if batch is None or r["batch"] == batch]

    def state(self):
        return json.loads((self.run_dir / "state.json").read_text())

    def batches(self):
        return {k: v["status"] for k, v in self.state()["osint"]["batches"].items()}


class BatchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.h = Harness(self._tmp.name)

    def test_batches_run_resume_and_retry_once(self):
        h = self.h
        h.plan(**{"batch-002": "fail-once", "batch-003": "fail"})
        code, counts = h.run()
        self.assertEqual(code, 1)
        self.assertEqual(h.batches(), {"batch-001": "done", "batch-002": "done", "batch-003": "failed"})
        self.assertEqual([len(h.calls(b)) for b in ("batch-001", "batch-002", "batch-003")], [1, 2, 2],
                         "a failed batch is retried once in the same run")
        self.assertEqual((counts["done"], counts["failed"], counts["batches"], counts["profiles"]), (2, 1, 3, 4))
        state = h.state()
        self.assertEqual(state["steps"], {"plan-agent": {"status": "done"}}, "other state is kept")
        self.assertEqual(state["osint"]["cli_version"], run_osint.CLAUDE_CODE_VERSION)
        three = state["osint"]["batches"]["batch-003"]
        self.assertEqual((three["attempts"], three["exit_code"], three["error"]), (2, 1, "claude exited 1"))
        two = state["osint"]["batches"]["batch-002"]
        self.assertEqual((two["attempts"], two["profiles"], two["boats"], two["missing"], two["num_turns"]),
                         (2, 2, 2, [], 7))

        # Resume: done batches are skipped; the failed one gets another try (and its one retry).
        code, counts = h.run()
        self.assertEqual((code, counts["skipped_done"]), (1, 2))
        self.assertEqual([len(h.calls(b)) for b in ("batch-001", "batch-002", "batch-003")], [1, 2, 4])

        h.plan()
        code, counts = h.run()
        self.assertEqual((code, counts["done"], counts["failed"], counts["skipped_done"]), (0, 3, 0, 2))
        self.assertEqual(len(h.calls("batch-003")), 5)
        self.assertEqual(h.state()["osint"]["batches"]["batch-003"]["attempts"], 5)
        self.assertEqual(len(list((h.run_dir / "profiles").glob("*.json"))), 5)

        code, counts = h.run()
        self.assertEqual((code, counts["skipped_done"]), (0, 3))
        self.assertEqual(len(h.calls()), 8, "a finished run starts no session")

    def test_a_running_batch_left_by_a_crash_is_run_again(self):
        state = json.loads((self.h.run_dir / "state.json").read_text())
        state["osint"] = {"batches": {"batch-001": {"status": "running", "attempts": 1}}}
        (self.h.run_dir / "state.json").write_text(json.dumps(state))
        code, _counts = self.h.run()
        self.assertEqual(code, 0)
        self.assertEqual(self.h.state()["osint"]["batches"]["batch-001"]["attempts"], 2)

    def test_batches_run_in_parallel_up_to_the_limit(self):
        h = Harness(Path(self._tmp.name) / "wide", boats=8, batch_size=2)
        h.plan(_sleep=0.6)
        code, _counts = h.run(parallel=2)
        self.assertEqual(code, 0)
        starts = sorted(c["start"] for c in h.calls())
        ends = sorted(json.loads(line)["end"] for line in (h.bin / "ends.jsonl").read_text().splitlines())
        events = sorted([(t, 1) for t in starts] + [(t, -1) for t in ends])
        running = peak = 0
        for _t, step in events:
            running += step
            peak = max(peak, running)
        self.assertEqual(peak, 2)

    def test_a_batch_over_its_time_limit_is_stopped_and_retried_once(self):
        self.h.plan(**{"batch-001": "hang"})
        started = time.monotonic()
        with mock.patch.object(run_osint, "KILL_GRACE_S", 2):
            code, _counts = self.h.run(timeout_min=0.02, max_batches=1)
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(code, 1)
        one = self.h.state()["osint"]["batches"]["batch-001"]
        self.assertEqual((one["status"], one["attempts"]), ("failed", 2))
        self.assertTrue(one["error"].startswith("timed out"), one["error"])

    def test_the_run_deadline_stops_the_run_and_leaves_the_rest_pending(self):
        self.h.plan(**{"batch-001": "hang"})
        started = time.monotonic()
        with mock.patch.object(run_osint, "KILL_GRACE_S", 2), mock.patch.object(run_osint, "MIN_SESSION_S", 1):
            code, counts = self.h.run(parallel=1, deadline_min=0.04)  # 2.4 s
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(code, 1, "a run the deadline cut short is red, so it gets resumed")
        self.assertEqual((counts["stopped"], counts["failed"], counts["not_run"], counts["done"]), ("deadline", 1, 2, 0))
        self.assertEqual([c["batch"] for c in self.h.calls()], ["batch-001"], "no batch starts too close to the deadline")
        batches = self.h.state()["osint"]["batches"]
        self.assertEqual((batches["batch-001"]["status"], batches["batch-001"]["attempts"]), ("failed", 1))
        self.assertIn("run deadline", batches["batch-001"]["error"])
        self.assertEqual(set(batches), {"batch-001"}, "the batches not started stay pending for a resume")

    def test_sigterm_stops_every_session_and_what_it_started(self):
        h = self.h
        h.plan(**{"batch-001": "hang-tree", "batch-002": "hang-tree", "batch-003": "hang-tree"})
        children = h.bin / "children.txt"

        def cancel_when_both_started():
            give_up = time.monotonic() + 20
            while time.monotonic() < give_up:
                if children.exists() and len(children.read_text().split()) >= 2:
                    os.kill(os.getpid(), signal.SIGTERM)  # as the Actions runner does on cancel
                    return
                time.sleep(0.05)

        previous = signal.getsignal(signal.SIGTERM)
        threading.Thread(target=cancel_when_both_started, daemon=True).start()
        started = time.monotonic()
        with mock.patch.object(run_osint, "CANCEL_GRACE_S", 1):
            code, counts = h.run(parallel=2)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous, "the handler is removed after the run")
        self.assertEqual((code, counts["stopped"], counts["not_run"]), (1, "SIGTERM", 1))
        self.assertEqual(sorted(c["batch"] for c in h.calls()), ["batch-001", "batch-002"],
                         "no batch starts after the signal, and nothing is retried")
        batches = h.state()["osint"]["batches"]
        self.assertEqual({b: batches[b]["error"] for b in batches},
                         {"batch-001": "stopped by SIGTERM", "batch-002": "stopped by SIGTERM"})
        # The sessions and the children they started (which ignore SIGTERM) are all gone.
        pids = [c["pid"] for c in h.calls()] + [int(p) for p in children.read_text().split()]
        give_up = time.monotonic() + 10
        while any(_alive(p) for p in pids) and time.monotonic() < give_up:
            time.sleep(0.1)
        self.assertEqual([p for p in pids if _alive(p)], [], "no orphaned session processes")

    def test_a_session_without_profiles_or_with_an_error_result_fails(self):
        self.h.plan(**{"batch-001": "no-profiles", "batch-002": "error-result"})
        code, _counts = self.h.run()
        self.assertEqual(code, 1)
        batches = self.h.state()["osint"]["batches"]
        self.assertEqual(batches["batch-001"]["error"], "no profiles written")
        self.assertEqual(batches["batch-002"]["error"], "session ended error_max_turns")
        self.assertEqual(batches["batch-003"]["status"], "done")

    def test_max_batches_limits_the_batches_attempted(self):
        code, counts = self.h.run(max_batches=1)
        self.assertEqual((code, counts["done"], counts["not_run"]), (0, 1, 2))
        self.assertEqual([c["batch"] for c in self.h.calls()], ["batch-001"])

    def test_a_manifest_that_writes_outside_the_run_is_refused(self):
        doc = json.loads((self.h.run_dir / "manifests" / "batch-002.json").read_text())
        doc["output_dir"] = str(Path(self._tmp.name) / "elsewhere")
        (self.h.run_dir / "manifests" / "batch-002.json").write_text(json.dumps(doc))
        code, _counts = self.h.run()
        self.assertEqual(code, 1)
        self.assertIn("output_dir", self.h.state()["osint"]["batches"]["batch-002"]["error"])
        self.assertEqual(self.h.calls("batch-002"), [])

    def test_each_session_is_locked_down(self):
        self.h.run(max_batches=1)
        (call,) = self.h.calls()
        argv, run_dir = call["argv"], self.h.run_dir
        self.assertEqual(Path(call["cwd"]).resolve(), run_dir.resolve(), "the run directory is the working directory")

        def value(flag):
            return argv[argv.index(flag) + 1]

        self.assertEqual(argv[0], "-p")
        self.assertEqual(value("--agent"), "charter-osint")
        agents = json.loads(Path(value("--agents")).read_text())
        self.assertEqual(set(agents), {"charter-osint"})
        self.assertEqual(agents["charter-osint"]["tools"], list(run_osint.TOOLS))
        self.assertIn("## Off-limits sources (D7)", agents["charter-osint"]["prompt"])
        self.assertEqual(value("--tools"), "Read,Write,Glob,Grep,WebFetch,WebSearch,Bash")
        self.assertEqual(value("--permission-mode"), "dontAsk")
        self.assertEqual(value("--permission-prompts"), "none")
        self.assertEqual(value("--setting-sources"), "", "no user, project or local settings file is loaded")
        self.assertEqual(value("--output-format"), "json")
        self.assertEqual(value("--max-turns"), str(run_osint.DEFAULT_MAX_TURNS))
        for flag in ("--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"):
            self.assertIn(flag, argv)
        allowed = re.split(r",(?![^(]*\))", value("--allowedTools"))
        cache = self.h.var / "CA" / "http-cache" / "agent"
        self.assertEqual(sorted(allowed), sorted([
            "WebFetch", "WebSearch", "Bash(python -m skippercast.fleet validate-profile *)",
            f"Edit(/{run_dir}/profiles/**)", f"Edit(/{run_dir}/summaries/**)", f"Edit(/{cache}/**)"]))
        self.assertNotIn("Read", allowed, "reads stay inside the working directories")
        self.assertFalse([rule for rule in allowed if rule.startswith("Bash") and "validate-profile" not in rule])
        denied = value("--disallowedTools").split(",")
        for host in (*HOSTS, "marinetraffic.com", "vesselfinder.com"):
            self.assertIn(f"WebFetch(domain:{host})", denied)
            self.assertIn(f"WebFetch(domain:*.{host})", denied)
        self.assertIn("mcp__*", denied)
        add = argv[argv.index("--add-dir") + 1:argv.index("--strict-mcp-config")]
        self.assertEqual(add, [str(ROOT / "schemas"), str(ROOT / "catalog/fleet"), str(cache)])
        manifest = run_dir / "manifests" / "batch-001.json"
        self.assertIn(f"batch manifest {manifest}", call["prompt"])
        self.assertIn(str(run_dir / "summaries" / "batch-001.md"), call["prompt"])
        # Only the allowlisted environment: the job's OIDC request token, GITHUB_TOKEN and the Places key never reach it.
        self.assertEqual(call["token"], "test-token-not-real")
        for name in ("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL", "GITHUB_TOKEN",
                     "GOOGLE_PLACES_API_KEY", "ANTHROPIC_API_KEY"):
            self.assertNotIn(name, call["env"])
        self.assertIn("DISABLE_AUTOUPDATER", call["env"])
        self.assertTrue(set(call["env"]) <= set(run_osint.PASS_ENV) | {
            "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "DISABLE_AUTOUPDATER", "PWD", "SHLVL", "_", "LC_CTYPE"},
            call["env"])

    def test_the_session_never_reads_the_runner_users_claude_settings(self):
        # The runner user's own config dir (with a permissive settings file) must not reach the session.
        home_config = Path(self._tmp.name) / "home-claude"
        home_config.mkdir()
        (home_config / "settings.json").write_text(json.dumps({"permissions": {"allow": ["Bash(*)"]}}))
        self.h.environ["CLAUDE_CONFIG_DIR"] = str(home_config)
        code, _counts = self.h.run(max_batches=1)
        self.assertEqual(code, 0)
        (call,) = self.h.calls()
        dedicated = self.h.var / "osint" / "claude-config"
        self.assertEqual(call["config_dir"], str(dedicated))
        self.assertEqual(dedicated.stat().st_mode & 0o777, 0o700)
        self.assertEqual(call["token"], "test-token-not-real", "the token comes from the environment")
        argv = call["argv"]
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        # A settings file or a stored login in the dedicated directory stops the run before any session.
        for name in ("settings.json", ".credentials.json"):
            with self.subTest(name=name):
                (dedicated / name).write_text("{}")
                with self.assertRaisesRegex(run_osint.Refused, re.escape(name)):
                    self.h.run()
                (dedicated / name).unlink()
        self.assertEqual(len(self.h.calls()), 1)


class AuthTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.h = Harness(self._tmp.name)

    def main(self, *extra, env=None):
        environ = {**self.h.environ, **(env or {})}
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, environ, clear=True), redirect_stdout(out), redirect_stderr(err):
            code = run_osint.main(["--region", "CA", "--run-id", RUN_ID, "--claude", str(self.h.claude), *extra])
        return code, out.getvalue(), err.getvalue()

    def test_exits_non_zero_when_an_api_key_is_set(self):
        for name, value in (("ANTHROPIC_API_KEY", "sk-not-real"), ("ANTHROPIC_API_KEY", ""),
                            ("ANTHROPIC_AUTH_TOKEN", "x"), ("CLAUDE_CODE_USE_BEDROCK", "1")):
            with self.subTest(name=name, value=value):
                code, out, err = self.main(env={name: value})
                self.assertEqual(code, 2)
                self.assertIn(name, err)
                self.assertNotIn("sk-not-real", err + out)
                self.assertEqual(self.h.calls(), [], "no session starts")
        self.assertFalse((self.h.run_dir / "osint").exists())

    def test_the_main_entry_runs_and_prints_counts_only(self):
        code, out, _err = self.main()
        self.assertEqual(code, 0)
        counts = json.loads(out)
        self.assertEqual((counts["done"], counts["batches"]), (3, 3))
        self.assertNotIn("Test Boat", out)

    def test_the_token_comes_from_a_private_env_file(self):
        env_file = Path(self._tmp.name) / "claude.env"
        env_file.write_text("# claude setup-token\nexport CLAUDE_CODE_OAUTH_TOKEN='file-token-not-real'\n")
        env_file.chmod(0o600)
        environ = {k: v for k, v in self.h.environ.items() if k != "CLAUDE_CODE_OAUTH_TOKEN"}
        code, _counts = run_osint.run("CA", RUN_ID, claude=str(self.h.claude), environ=environ, auth_file=env_file,
                                      max_batches=1)
        self.assertEqual(code, 0)
        self.assertEqual(self.h.calls()[0]["token"], "file-token-not-real")
        env_file.chmod(0o644)
        with self.assertRaisesRegex(run_osint.Refused, "0600"):
            run_osint.run("CA", RUN_ID, claude=str(self.h.claude), environ=environ, auth_file=env_file)
        env_file.write_text("CLAUDE_CODE_OAUTH_TOKEN=x\nANTHROPIC_API_KEY=y\n")
        env_file.chmod(0o600)
        with self.assertRaisesRegex(run_osint.Refused, "ANTHROPIC_API_KEY"):
            run_osint.run("CA", RUN_ID, claude=str(self.h.claude), environ=environ, auth_file=env_file)
        with self.assertRaisesRegex(run_osint.Refused, "setup-token"):
            run_osint.run("CA", RUN_ID, claude=str(self.h.claude), environ=environ,
                          auth_file=Path(self._tmp.name) / "none.env")

    def test_refuses_another_cli_version_or_another_credential(self):
        (self.h.bin / "version").write_text("2.0.0 (Claude Code)\n")
        with self.assertRaisesRegex(run_osint.Refused, "pinned"):
            self.h.run()
        (self.h.bin / "version").unlink()
        (self.h.bin / "auth.json").write_text(json.dumps({"loggedIn": True, "authMethod": "api_key_helper"}))
        with self.assertRaisesRegex(run_osint.Refused, "oauth_token"):
            self.h.run()
        self.assertEqual(self.h.calls(), [])

    def test_refuses_a_run_without_plan_agent_output(self):
        (self.h.run_dir / "agent-plan.json").unlink()
        with self.assertRaisesRegex(run_osint.Refused, "plan-agent"):
            self.h.run()
        code, _out, err = self.main("--run-id", "not-a-run")
        self.assertEqual(code, 2)


def _section(text, heading):
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not match:
        raise AssertionError(f"no '## {heading}' section")
    return match.group(1)


class AgentContractTests(unittest.TestCase):
    """charter-osint.md against catalog/fleet/off-limits.json (D7) and agent.py's manifests."""

    def setUp(self):
        self.text = AGENT_MD.read_text(encoding="utf-8")

    def test_no_off_limits_host_is_a_fetchable_source(self):
        fetchable = _section(self.text, "Sources you may fetch").lower()
        squashed = re.sub(r"[\s\-]", "", fetchable)
        for host in HOSTS:
            label = host.split(".")[0]
            with self.subTest(host=host):
                self.assertNotIn(host, fetchable)
                self.assertNotRegex(fetchable, rf"\b{re.escape(label)}\b")
                if len(label) >= 8:
                    self.assertNotIn(label, squashed)
        for brand in ("fish city", "fishingbooker", "fareharbor", "xola", "fishdope", "instagram", "facebook",
                      "marinetraffic", "vesselfinder"):
            self.assertNotIn(brand, fetchable)

    def test_trackers_not_yet_cleared_are_listed_and_denied(self):
        pending = _section(self.text, "Not yet cleared")
        self.assertEqual(run_osint.NOT_CLEARED, ("marinetraffic.com", "vesselfinder.com"))
        for host in run_osint.NOT_CLEARED:
            self.assertIn(f"`{host}`", pending)
            self.assertNotIn(host.split(".")[0], re.sub(r"[\s\-]", "", _section(self.text, "Sources you may fetch").lower()))
        self.assertIn("open-questions.md` Q16", pending)
        self.assertIn("## Q16. MarineTraffic and VesselFinder", (ROOT / "docs/plans/charter-fleet/open-questions.md")
                      .read_text(encoding="utf-8"))

    def test_lists_every_off_limits_host_and_the_handle_rule(self):
        off = _section(self.text, "Off-limits sources (D7)")
        for host in HOSTS:
            self.assertIn(f"`{host}`", off)
        self.assertIn("catalog/fleet/off-limits.json", off)
        rule = " ".join(off.split())
        self.assertIn("An Instagram or Facebook handle, a profile URL or a booking-platform link on one of these hosts "
                      "may be recorded as a value only when it is found on the operator's own site, a landing page or "
                      "a report site, and that page is the `source_url`", rule)
        self.assertIn("A handle seen only in a web search result is not recorded.", rule)
        self.assertIn("Never fetch, search inside or cite as `source_url`", rule)

    def test_states_the_manifest_contract_agent_py_writes(self):
        contract = _section(self.text, "Manifest contract")
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "CA" / "runs" / RUN_ID
            stale = dict(vessel(1), last_profiled_at="2026-01-01T00:00:00Z", website="https://boat.example/")
            (doc,) = agent.manifests("CA", RUN_ID, run_dir, "2026-10-11T10:17:00Z", [(stale, ["stale"])])
        for key in doc:
            self.assertIn(f"`{key}`", contract)
        for key in doc["policy"]:
            self.assertIn(f"`{key}`", contract)
        for key in doc["boats"][0]:
            self.assertIn(f"`{key}`", contract)
        for key in (*agent.KNOWN, "last_profiled_at", "focus"):
            self.assertIn(f"`{key}`", contract)
        self.assertIn(f"`{doc['output_file']}`", contract)
        self.assertIn(f"`{doc['schema']}`", contract)
        self.assertIn(f"`{doc['validate']}`", contract)
        self.assertIn(f"`manifest_version`: `{agent.MANIFEST_VERSION}`", contract)

    def test_the_agent_tools_are_the_runner_allowlist(self):
        definition = run_osint.agent_definition(AGENT_MD)["charter-osint"]
        self.assertEqual(definition["tools"], list(run_osint.TOOLS))
        self.assertEqual(definition["model"], "claude-opus-5-5")
        self.assertTrue(definition["omitClaudeMd"])
        with tempfile.TemporaryDirectory() as tmp:
            drifted = Path(tmp) / "charter-osint.md"
            drifted.write_text(self.text.replace("tools: Read, Write,", "tools: Read, Write, Edit,"))
            with self.assertRaisesRegex(run_osint.Refused, "tools"):
                run_osint.agent_definition(drifted)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()
        self.header = "\n".join(line for line in self.text.split("\njobs:", 1)[0].splitlines()
                                if not line.lstrip().startswith("#"))

    def test_never_triggers_on_pull_request(self):
        on = re.search(r"\non:\n((?:[ \t].*\n?)*)", self.header + "\n").group(1)
        self.assertEqual(re.findall(r"^  ([a-z_]+):", on, re.M), ["schedule", "workflow_dispatch"])
        for trigger in ("pull_request", "pull_request_target", "push:", "workflow_run"):
            self.assertNotIn(trigger, self.header)
        self.assertIn('- cron: "17 10 * * 0"', on)
        self.assertEqual(re.findall(r"^      ([a-z_]+):\n", on, re.M), ["region", "mode", "sink", "max_batches", "run_id"])

    def test_dark_main_only_on_our_runner_with_least_privilege(self):
        self.assertIn("if: vars.ENABLE_FLEET == 'true' && vars.DATA_RUNNER != '' && github.ref == 'refs/heads/main'",
                      self.text)
        self.assertEqual(re.findall(r"^\s*runs-on:\s*(.+?)\s*$", self.text, re.M),
                         ["${{ vars.DATA_RUNNER || 'ubuntu-latest' }}"])
        self.assertIn("permissions: {}", self.header)
        granted = sorted(re.sub(r"\s*#.*", "", line).strip() for line in
                         re.search(r"\n    permissions:\n((?:      .*\n)+)", self.text).group(1).splitlines())
        self.assertEqual(granted, ["contents: read", "id-token: write"])
        self.assertNotIn("secrets.", self.text, "the subscription token stays on the box, not in GitHub")
        self.assertNotIn("ANTHROPIC_API_KEY:", self.text)
        self.assertIn("persist-credentials: false", self.text)
        self.assertIn("group: fleet-osint", self.header)

    def test_inputs_reach_the_shell_only_through_the_environment(self):
        for line in self.text.split("\njobs:", 1)[1].splitlines():
            if "${{" in line:
                self.assertRegex(line.strip(), r"^(?:[A-Z_]+|runs-on|group): \$\{\{ [^}]+ \}\}$", line)

    def test_plans_researches_with_the_pinned_cli_and_ingests(self):
        self.assertIn("python scripts/fleet/run_osint.py --print-cli-version", self.text)
        self.assertIn('"@anthropic-ai/claude-code@$version"', self.text)
        self.assertIn('plan-agent --region "$REGION" --sink "$SINK" --run-id "$RUN_ID" --mode "$MODE"', self.text)
        self.assertIn('python scripts/fleet/run_osint.py "${args[@]}"', self.text)
        self.assertIn('--profiles "$run_dir/profiles"', self.text)
        self.assertIn("FLEET_OSINT_PARALLEL: ${{ vars.FLEET_OSINT_PARALLEL || '3' }}", self.text)
        self.assertNotIn("GITHUB_WORKSPACE", self.text)

    def test_the_run_deadline_leaves_the_job_time_to_ingest(self):
        (job,) = [int(m) for m in re.findall(r"^    timeout-minutes: (\d+)$", self.text, re.M)]
        # The deadline, one cut session's grace, and at least half an hour for setup and Ingest.
        self.assertLessEqual(run_osint.DEFAULT_DEADLINE_MIN + run_osint.KILL_GRACE_S / 60 + 30, job)

    def test_the_pin_is_documented_with_its_flags(self):
        runbook = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn(f"`{run_osint.CLAUDE_CODE_VERSION}`", runbook)
        for flag in ("--agents", "--agent", "--tools", "--allowedTools", "--disallowedTools", "--permission-mode",
                     "--permission-prompts", "--max-turns", "--output-format", "--add-dir", "--strict-mcp-config",
                     "--no-session-persistence", "--setting-sources", "CLAUDE_CONFIG_DIR", "claude setup-token",
                     "ENABLE_FLEET",
                     "~/.config/skippercast/claude.env"):
            self.assertIn(flag, runbook)


if __name__ == "__main__":
    unittest.main()
