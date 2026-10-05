#!/usr/bin/env python3
"""Headless OSINT runner: the ``enrich-agent`` step (charter fleet design section 8, CF-21).

    python scripts/fleet/run_osint.py --region CA --run-id <run id> [--claude PATH]
        [--parallel N] [--max-batches N] [--timeout-min 60] [--max-turns 200] [--deadline-min 300]

Runs each batch manifest that ``plan-agent`` wrote (``<run_dir>/manifests/batch-NNN.json``)
as one ``claude -p`` session with the ``charter-osint`` agent, up to ``--parallel``
(``FLEET_OSINT_PARALLEL``, default 3) at once, ``--timeout-min`` (60) per batch. Each
session works in the run directory, writes ``profiles/<vessel_id>.json`` and
``summaries/<batch_id>.md``, and its JSON result goes to ``osint/<batch_id>.json``.
``ingest --profiles <run_dir>/profiles`` then validates and pushes the profiles.

**Resume.** Each batch's status is recorded under ``osint`` in the run's ``state.json``.
A re-run with the same run id skips ``done`` batches; a batch that fails is retried once
in the same invocation, and a re-run tries the still-failed ones again.

**Run deadline.** ``--deadline-min`` (300, below ``fleet-osint.yml``'s 360-minute job
timeout) bounds the whole invocation, so the workflow's Ingest step always runs: no batch
starts with less than ``MIN_SESSION_S`` left, a running session is cut at the deadline,
and the batches left over stay pending for a resume. On SIGTERM or SIGINT (a cancelled
job) every live session's process group gets SIGTERM, then SIGKILL after
``CANCEL_GRACE_S``, and no further batch starts, so no ``claude`` process outlives the job.

**Subscription auth only.** The runner exits 2 when ``ANTHROPIC_API_KEY`` (or
``ANTHROPIC_AUTH_TOKEN``, or a cloud-provider switch) is in its environment, so a run can
never bill the API. The session authenticates with ``CLAUDE_CODE_OAUTH_TOKEN`` from
``claude setup-token``: taken from the environment, else from the 0600 env file
``~/.config/skippercast/claude.env`` (``--auth-file``). Before the first batch,
``claude --version`` must equal ``CLAUDE_CODE_VERSION`` and ``claude auth status`` must
report ``authMethod`` ``oauth_token`` (an ``apiKeyHelper`` would outrank the token).

**Session lockdown.** The agent definition is ``.claude/agents/charter-osint.md``, passed
with ``--agents <file> --agent charter-osint`` (its body replaces the system prompt; its
``tools`` must be ``TOOLS``). ``--tools`` limits the built-in tools to ``TOOLS``;
``--permission-mode dontAsk`` with ``--permission-prompts none`` denies every call not
pre-approved; ``--allowedTools`` approves WebFetch, WebSearch, writes under ``profiles/``,
``summaries/`` and the manifest's cache directory, and Bash for the profile validator
only; ``--disallowedTools`` denies WebFetch to every host in ``catalog/fleet/off-limits.json``
and its subdomains, and every MCP tool. Those rules hold only if no settings file adds
allow rules, so no settings file is read: ``--setting-sources ""`` loads none of the user,
project and local files, and ``CLAUDE_CONFIG_DIR`` is a dedicated directory the runner owns
(``<fleet var>/osint/claude-config``), never the runner user's ``~/.claude``; the runner
refuses to start when that directory holds a ``settings.json`` or a ``.credentials.json``,
so the token comes from the environment only. The session's environment is an allowlist
(``PASS_ENV``), so the job's OIDC request token and ``GITHUB_TOKEN`` never reach it.
These flags were checked against ``claude --help`` and the CLI reference for the pinned
version (``--max-turns`` is documented but not listed by ``--help``).

Exit status: 0 when every batch attempted is done, 1 when any failed after its retry or
the deadline or a signal stopped the run early (the done ones' profiles can still be
ingested), 2 on a refusal or setup error. Prints
counts only (no boat names, no agent output): workflow logs are public.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from skippercast.fleet.runs import RUN_ID, fleet_var  # noqa: E402

CLAUDE_CODE_VERSION = "2.1.289"  # npm @anthropic-ai/claude-code; flags below verified against this version
AGENT = "charter-osint"
AGENT_FILE = ROOT / ".claude" / "agents" / f"{AGENT}.md"
OFF_LIMITS = ROOT / "catalog" / "fleet" / "off-limits.json"
SCHEMA_DIR = ROOT / "schemas"
TOOLS = ("Read", "Write", "Glob", "Grep", "WebFetch", "WebSearch", "Bash")
VALIDATOR = "python -m skippercast.fleet validate-profile"
DEFAULT_PARALLEL = 3
DEFAULT_TIMEOUT_MIN = 60
DEFAULT_MAX_TURNS = 200
DEFAULT_DEADLINE_MIN = 300  # fleet-osint.yml's job timeout is 360: leave an hour for Ingest
MIN_SESSION_S = 300  # do not start a batch with less than this left before the deadline
CANCEL_GRACE_S = 5  # SIGTERM to SIGKILL on cancel; Actions escalates within about 10 s
ATTEMPTS_PER_RUN = 2  # the first try and one retry
KILL_GRACE_S = 30
MANIFEST_VERSION = 1
BATCH = re.compile(r"^batch-[0-9]{3}$")
# Any of these makes the session bill something other than the subscription.
REFUSED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
               "CLAUDE_CODE_USE_FOUNDRY")
TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"
# The only variables the session sees (plus the token and DISABLE_AUTOUPDATER).
PASS_ENV = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR", "SHELL", "TERM",
            "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
            "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE",
            "VIRTUAL_ENV", "PYTHONPATH", "SKIPPERCAST_FLEET_VAR", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
            "XDG_CACHE_HOME")
CONFIG_DIR = "CLAUDE_CONFIG_DIR"
# Files that must never be in the session's config directory: user settings could add allow
# rules, and a stored login could stand in for the token (which must come from the environment).
CONFIG_REFUSED = ("settings.json", "settings.local.json", ".credentials.json")
DEFAULT_AUTH_FILE = Path("~/.config/skippercast/claude.env")


class Refused(Exception):
    """A setup problem or a refusal: the runner exits 2 before any batch runs."""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- auth and environment ------------------------------------------------------------------

def refuse_billing_env(environ: Mapping[str, str]) -> None:
    present = [name for name in REFUSED_ENV if name in environ]
    if present:
        raise Refused(f"{', '.join(present)} is set: the OSINT run uses the Claude subscription only "
                      "(CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`); unset it and run again")


def read_env_file(path: Path) -> dict[str, str]:
    """``KEY=VALUE`` lines (``export`` and quotes allowed) from a file only its owner can read."""
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise Refused(f"{path}: mode {stat.S_IMODE(mode):04o}; the token file must be 0600 (chmod 600 {path})")
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        out[key.strip()] = value.strip().strip("'\"")
    return out


def oauth_token(environ: Mapping[str, str], auth_file: Path) -> str:
    if environ.get(TOKEN):
        return environ[TOKEN]
    path = auth_file.expanduser()
    if not path.is_file():
        raise Refused(f"no {TOKEN} in the environment and no {path}: on the runner, as its user, run "
                      "`claude setup-token` and save the token there (docs/operations/runbooks/fleet-osint.md)")
    values = read_env_file(path)
    refuse_billing_env(values)
    if not values.get(TOKEN):
        raise Refused(f"{path} has no {TOKEN}")
    return values[TOKEN]


def claude_config_dir(environ: Mapping[str, str]) -> Path:
    """The session's own ``CLAUDE_CONFIG_DIR`` (``<fleet var>/osint/claude-config``), created 0700."""
    path = fleet_var(environ) / "osint" / "claude-config"
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    present = [name for name in CONFIG_REFUSED if (path / name).exists()]
    if present:
        raise Refused(f"{path} holds {', '.join(present)}: the OSINT session's config directory must have no "
                      "settings and no stored login (the token comes from the environment); remove them")
    return path


def session_env(environ: Mapping[str, str], token: str, config_dir: Path) -> dict[str, str]:
    env = {name: environ[name] for name in PASS_ENV if name in environ}
    env[TOKEN] = token
    env[CONFIG_DIR] = str(config_dir)  # never the runner user's ~/.claude and its settings
    env["DISABLE_AUTOUPDATER"] = "1"  # keep the pinned version
    return env


def check_cli(claude: str, env: Mapping[str, str]) -> None:
    """The pinned version, signed in with the subscription token."""
    try:
        version = subprocess.run([claude, "--version"], env=env, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refused(f"{claude} --version: {type(error).__name__}: {error}") from None
    found = (version.stdout.split() or ["?"])[0]
    if version.returncode != 0 or found != CLAUDE_CODE_VERSION:
        raise Refused(f"Claude Code {found} found, {CLAUDE_CODE_VERSION} pinned (scripts/fleet/run_osint.py "
                      "CLAUDE_CODE_VERSION; the workflow installs it)")
    try:
        status = subprocess.run([claude, "auth", "status", "--json"], env=env, capture_output=True, text=True,
                                timeout=60)
        auth = json.loads(status.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        raise Refused(f"{claude} auth status: {type(error).__name__}") from None
    if auth.get("authMethod") != "oauth_token" or auth.get("apiProvider", "firstParty") != "firstParty":
        raise Refused(f"claude auth status reports authMethod {auth.get('authMethod')!r}, provider "
                      f"{auth.get('apiProvider')!r}; the run needs the subscription token (oauth_token, firstParty)")


# ---- the agent and the session -------------------------------------------------------------

def agent_definition(path: Path = AGENT_FILE) -> dict[str, Any]:
    """``--agents`` JSON from the agent file: front matter fields and the body as ``prompt``."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not match:
        raise Refused(f"{path}: no front matter")
    meta: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    if meta.get("name") != AGENT:
        raise Refused(f"{path}: name is {meta.get('name')!r}, not {AGENT}")
    tools = tuple(t.strip() for t in meta.get("tools", "").split(",") if t.strip())
    if set(tools) != set(TOOLS):
        raise Refused(f"{path}: tools {', '.join(tools)} differ from the runner's {', '.join(TOOLS)}")
    agent: dict[str, Any] = {"description": meta["description"], "prompt": match.group(2).strip() + "\n",
                             "tools": list(TOOLS)}
    for key in ("model", "effort"):
        if meta.get(key):
            agent[key] = meta[key]
    if meta.get("omitClaudeMd") == "true":
        agent["omitClaudeMd"] = True
    return {AGENT: agent}


def off_limits_hosts(path: Path = OFF_LIMITS) -> list[str]:
    hosts = [h["host"] for h in json.loads(path.read_text(encoding="utf-8"))["hosts"]]
    if not hosts:
        raise Refused(f"{path}: no hosts; the off-limits list is never empty")
    return hosts


def absolute(path: Path) -> str:
    """A permission-rule path anchored at the filesystem root (``//`` prefix)."""
    return "//" + str(path).lstrip("/")


def command(claude: str, run_dir: Path, cache_dir: Path, agents_file: Path, hosts, max_turns: int) -> list[str]:
    allowed = ["WebFetch", "WebSearch", f"Bash({VALIDATOR} *)"]
    allowed += [f"Edit({absolute(d)}/**)" for d in (run_dir / "profiles", run_dir / "summaries", cache_dir)]
    denied = [rule for host in hosts for rule in (f"WebFetch(domain:{host})", f"WebFetch(domain:*.{host})")]
    denied.append("mcp__*")
    return [claude, "-p",
            "--agents", str(agents_file), "--agent", AGENT,
            "--tools", ",".join(TOOLS),
            "--allowedTools", ",".join(allowed),
            "--disallowedTools", ",".join(denied),
            "--permission-mode", "dontAsk",
            "--permission-prompts", "none",
            "--setting-sources", "",  # no user, project or local settings file can add allow rules
            "--max-turns", str(max_turns),
            "--output-format", "json",
            "--add-dir", str(SCHEMA_DIR), str(OFF_LIMITS.parent), str(cache_dir),
            "--strict-mcp-config",
            "--no-session-persistence",
            "--disable-slash-commands"]


def prompt(manifest: Path, doc: Mapping[str, Any], summary: Path) -> str:
    return (f"Research the boats in the batch manifest {manifest}. Read it first and follow the manifest contract "
            f"in your instructions: write one profile per boat to {doc['output_dir']}/<vessel_id>.json, validate "
            f"each with `{VALIDATOR} <file>`, cache fetched pages under {doc['policy']['cache_dir']}, and write the "
            f"batch summary to {summary}. Paths in the manifest that are not absolute (schema, policy.off_limits) "
            f"are relative to {ROOT}. Then reply with your summary.\n")


# ---- batches -------------------------------------------------------------------------------

def load_manifest(path: Path, region: str, run_id: str, run_dir: Path) -> dict:
    """A manifest this run wrote: version, region, run and batch ids, and an output_dir inside the run."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    if doc.get("manifest_version") != MANIFEST_VERSION:
        problems.append(f"manifest_version {doc.get('manifest_version')!r}")
    if doc.get("region") != region or doc.get("run_id") != run_id:
        problems.append("region or run_id is not this run's")
    if doc.get("batch_id") != path.stem or not BATCH.match(path.stem):
        problems.append(f"batch_id {doc.get('batch_id')!r} does not match the file name")
    if Path(str(doc.get("output_dir"))).resolve() != (run_dir / "profiles").resolve():
        problems.append("output_dir is not <run_dir>/profiles")
    if not isinstance((doc.get("policy") or {}).get("cache_dir"), str) or not doc.get("boats"):
        problems.append("no policy.cache_dir or no boats")
    if problems:
        raise ValueError("; ".join(problems))
    return doc


class State:
    """``state.json``'s ``osint`` section, written atomically after each change."""

    def __init__(self, path: Path):
        self.path, self.lock = path, threading.Lock()
        self.doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self.osint = self.doc.setdefault("osint", {})
        self.batches = self.osint.setdefault("batches", {})

    def update(self, batch: str, **fields) -> None:
        with self.lock:
            self.batches.setdefault(batch, {"attempts": 0}).update(fields)
            self.osint.update(cli_version=CLAUDE_CODE_VERSION, updated_at=now())
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            tmp.replace(self.path)


class Live:
    """The running sessions' process groups, and the stop switch a signal or the deadline throws."""

    def __init__(self):
        self.lock, self.pids, self.stop = threading.Lock(), set(), threading.Event()
        self.reason: str | None = None

    def add(self, pid: int) -> None:
        with self.lock:
            self.pids.add(pid)
            stopping = self.stop.is_set()
        if stopping:  # started while a cancel was under way
            self._signal([pid], signal.SIGTERM)

    def discard(self, pid: int) -> None:
        with self.lock:
            self.pids.discard(pid)

    def cancel(self, reason: str, grace_s: float) -> None:
        """No further batch starts; live sessions get SIGTERM now and SIGKILL after ``grace_s``."""
        with self.lock:
            if self.stop.is_set():
                return
            self.reason = reason
            self.stop.set()
            pids = list(self.pids)
        self._signal(pids, signal.SIGTERM)
        timer = threading.Timer(grace_s, self._kill_rest)
        timer.daemon = True
        timer.start()

    def _kill_rest(self) -> None:
        with self.lock:
            pids = list(self.pids)
        self._signal(pids, signal.SIGKILL)

    @staticmethod
    def _signal(pids, sig) -> None:
        for pid in pids:
            try:
                os.killpg(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass


def run_session(cmd: list[str], text: str, cwd: Path, env: Mapping[str, str], out: Path, err: Path,
                timeout_s: float, live: Live | None = None) -> tuple[int | None, bool]:
    """(exit code, timed out). The prompt goes on stdin; on timeout the session's process group gets
    SIGTERM, then SIGKILL after ``KILL_GRACE_S``. ``live`` tracks the group so a cancel can stop it."""
    live = live or Live()
    with out.open("wb") as stdout, err.open("wb") as stderr:
        proc = subprocess.Popen(cmd, cwd=cwd, env=dict(env), stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                start_new_session=True)
        live.add(proc.pid)
        try:
            return _wait(proc, text, timeout_s)
        finally:
            live.discard(proc.pid)
            # Whatever the session started in its group (a tool's child) goes with it.
            Live._signal([proc.pid], signal.SIGKILL)


def _wait(proc: subprocess.Popen, text: str, timeout_s: float) -> tuple[int | None, bool]:
    try:
        proc.stdin.write(text.encode("utf-8"))
        proc.stdin.close()
    except BrokenPipeError:
        pass
    try:
        return proc.wait(timeout=timeout_s), False
    except subprocess.TimeoutExpired:
        for sig, grace in ((signal.SIGTERM, KILL_GRACE_S), (signal.SIGKILL, None)):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                break
            try:
                proc.wait(timeout=grace)
                break
            except subprocess.TimeoutExpired:
                continue
        proc.wait()
        return proc.returncode, True


def run_batch(path: Path, doc: dict, ctx: dict, state: State) -> bool | None:
    """True when done, False when failed, None when not started (stopped, or too close to the deadline)."""
    batch, run_dir, live = doc["batch_id"], ctx["run_dir"], ctx["live"]
    remaining = ctx["deadline"] - time.monotonic()
    if live.stop.is_set():
        return None
    if remaining < MIN_SESSION_S:
        ctx["deadline_hit"].set()
        return None
    timeout_s = min(ctx["timeout_s"], remaining)
    attempts = state.batches.get(batch, {}).get("attempts", 0) + 1
    state.update(batch, status="running", attempts=attempts, started_at=now(), finished_at=None, error=None)
    cache_dir = Path(doc["policy"]["cache_dir"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    summary = run_dir / "summaries" / f"{batch}.md"
    out, err = run_dir / "osint" / f"{batch}.json", run_dir / "osint" / f"{batch}.stderr.log"
    cmd = command(ctx["claude"], run_dir, cache_dir, ctx["agents_file"], ctx["hosts"], ctx["max_turns"])
    code, timed_out = ctx["session"](cmd, prompt(path, doc, summary), run_dir, ctx["env"], out, err, timeout_s,
                                     live=live)
    try:
        result = json.loads(out.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        result = {}
    boats = [b["vessel_id"] for b in doc["boats"]]
    written = [v for v in boats if (run_dir / "profiles" / f"{v}.json").is_file()]
    if live.stop.is_set() and (timed_out or code != 0):
        error = f"stopped by {live.reason}"
    elif timed_out and timeout_s < ctx["timeout_s"]:
        ctx["deadline_hit"].set()
        error = f"stopped at the run deadline ({ctx['deadline_min']:g} min)"
    elif timed_out:
        error = f"timed out after {ctx['timeout_s'] / 60:g} min"
    elif code != 0:
        error = f"claude exited {code}"
    elif result.get("is_error") or result.get("subtype") != "success":
        error = f"session ended {result.get('subtype') or 'without a result'}"
    elif not written:
        error = "no profiles written"
    else:
        error = None
    state.update(batch, status="failed" if error else "done", finished_at=now(), exit_code=code, error=error,
                 boats=len(boats), profiles=len(written), missing=sorted(set(boats) - set(written)),
                 num_turns=result.get("num_turns"), subtype=result.get("subtype"),
                 denials=len(result.get("permission_denials") or ()))
    return error is None


def run(region: str, run_id: str, *, claude: str = "claude", parallel: int = DEFAULT_PARALLEL,
        max_batches: int | None = None, timeout_min: float = DEFAULT_TIMEOUT_MIN, max_turns: int = DEFAULT_MAX_TURNS,
        deadline_min: float = DEFAULT_DEADLINE_MIN, auth_file: Path = DEFAULT_AUTH_FILE,
        environ: Mapping[str, str] | None = None, session: Callable = run_session) -> tuple[int, dict]:
    started = time.monotonic()
    environ = os.environ if environ is None else environ
    refuse_billing_env(environ)
    if not RUN_ID.match(run_id):
        raise Refused(f"run id {run_id!r} does not match YYYYMMDDTHHMMSSZ-xxxxxx")
    if not 1 <= parallel <= 8:
        raise Refused("--parallel takes 1-8")
    if not deadline_min > 0:
        raise Refused("--deadline-min takes a positive number")
    run_dir = fleet_var(environ) / region / "runs" / run_id
    if not (run_dir / "agent-plan.json").is_file():
        raise Refused(f"{run_dir}: no plan-agent output; run `python -m skippercast.fleet plan-agent` first")
    manifests = sorted((run_dir / "manifests").glob("batch-*.json"))
    env = session_env(environ, oauth_token(environ, auth_file), claude_config_dir(environ))
    claude_path = shutil.which(claude, path=env.get("PATH")) or claude
    check_cli(claude_path, env)
    for sub in ("profiles", "summaries", "osint"):
        (run_dir / sub).mkdir(exist_ok=True)
    agents_file = run_dir / "osint" / "agents.json"
    agents_file.write_text(json.dumps(agent_definition(), indent=2) + "\n", encoding="utf-8")
    ctx = {"run_dir": run_dir, "claude": claude_path, "agents_file": agents_file, "hosts": off_limits_hosts(),
           "max_turns": max_turns, "timeout_s": timeout_min * 60, "env": env, "session": session,
           "live": Live(), "deadline": started + deadline_min * 60, "deadline_min": deadline_min,
           "deadline_hit": threading.Event()}
    state = State(run_dir / "state.json")
    todo, skipped = [], 0
    for path in manifests:
        if state.batches.get(path.stem, {}).get("status") == "done":
            skipped += 1
            continue
        try:
            todo.append((path, load_manifest(path, region, run_id, run_dir)))
        except (OSError, ValueError, KeyError) as error:
            state.update(path.stem, status="failed", error=f"invalid manifest: {error}"[:300], finished_at=now())
    pending = todo[max_batches:] if max_batches is not None else []
    todo = todo[:max_batches] if max_batches is not None else todo
    unstarted: set[str] = set()
    with cancel_on_signals(ctx["live"]):
        for _attempt in range(ATTEMPTS_PER_RUN):
            if not todo or ctx["live"].stop.is_set():
                break
            with ThreadPoolExecutor(max_workers=parallel) as pool:
                futures = [pool.submit(run_batch, path, doc, ctx, state) for path, doc in todo]
                # Wake every second: a signal that lands on a worker thread runs its Python handler
                # only when the main thread executes bytecode.
                while wait(futures, timeout=1).not_done:
                    pass
                results = [future.result() for future in futures]
            unstarted |= {item[0].stem for item, result in zip(todo, results) if result is None}
            todo = [item for item, result in zip(todo, results) if result is False]
    statuses = {p.stem: state.batches.get(p.stem, {}).get("status") for p in manifests}
    values = list(statuses.values())
    stopped = ctx["live"].reason or ("deadline" if ctx["deadline_hit"].is_set() else None)
    counts = {"run_id": run_id, "batches": len(manifests), "skipped_done": skipped,
              "done": values.count("done"), "failed": values.count("failed"),
              "not_run": len(pending) + sum(1 for b in unstarted if statuses[b] not in ("done", "failed")),
              "stopped": stopped,
              "profiles": len(list((run_dir / "profiles").glob("*.json")))}
    return (1 if counts["failed"] or stopped else 0), counts


@contextmanager
def cancel_on_signals(live: Live):
    """While batches run, SIGTERM and SIGINT (a cancelled job) stop every live session."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def handler(signum, _frame):
        live.cancel(signal.Signals(signum).name, CANCEL_GRACE_S)

    previous = {sig: signal.signal(sig, handler) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        yield
    finally:
        for sig, old in previous.items():
            signal.signal(sig, old)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_osint.py", description=__doc__.splitlines()[0])
    parser.add_argument("--region", help="fleet region id, e.g. CA")
    parser.add_argument("--run-id", help="the plan-agent run whose manifests to research")
    parser.add_argument("--claude", default="claude", help="the Claude Code CLI (default: claude on PATH)")
    parser.add_argument("--parallel", type=int, default=None,
                        help=f"batches at once (default FLEET_OSINT_PARALLEL or {DEFAULT_PARALLEL})")
    parser.add_argument("--max-batches", type=int, default=None, help="research at most this many pending batches")
    parser.add_argument("--timeout-min", type=float, default=DEFAULT_TIMEOUT_MIN, help="minutes per batch (60)")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS, help="agentic turns per batch (200)")
    parser.add_argument("--deadline-min", type=float, default=DEFAULT_DEADLINE_MIN,
                        help=f"minutes for the whole run ({DEFAULT_DEADLINE_MIN}); later batches stay pending")
    parser.add_argument("--auth-file", type=Path, default=DEFAULT_AUTH_FILE,
                        help="0600 env file with CLAUDE_CODE_OAUTH_TOKEN (default ~/.config/skippercast/claude.env)")
    parser.add_argument("--print-cli-version", action="store_true", help="print the pinned Claude Code version")
    args = parser.parse_args(argv)
    if args.print_cli_version:
        print(CLAUDE_CODE_VERSION)
        return 0
    if not args.region or not args.run_id:
        parser.error("--region and --run-id are required")
    if args.max_batches is not None and args.max_batches < 1:
        parser.error("--max-batches takes a positive number")
    try:
        parallel = args.parallel or int(os.environ.get("FLEET_OSINT_PARALLEL") or DEFAULT_PARALLEL)
        code, counts = run(args.region, args.run_id, claude=args.claude, parallel=parallel,
                           max_batches=args.max_batches, timeout_min=args.timeout_min, max_turns=args.max_turns,
                           deadline_min=args.deadline_min, auth_file=args.auth_file)
    except (Refused, ValueError, OSError) as error:
        print(f"run_osint: {error}", file=sys.stderr)
        return 2
    print(json.dumps(counts, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
