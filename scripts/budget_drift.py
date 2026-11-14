#!/usr/bin/env python3
"""Budget drift (SC-CI-2): keep every size budget a margin above main, and record each move with its cause.

Why: 5 of main's 24 red fixes in 14 days (#1895, #1907, #1943, #2119, #2170) were a size budget a few bytes too
tight (landing scripts 12 B over, app styles 52 B over, pack shell 63 B, 4 B and 198 B over). Each one held every merge
in the repository until a fix pull request was reviewed. A budget now behaves like this:

* It fails only above its number (unchanged), and passes with a WARN from 97% of it (check_perf_budget.py and
  check_client.mjs print the warning; in GitHub Actions it is an annotation).
* This script, run on main by .github/workflows/budget-drift.yml after a build, finds every budget at or above 97%
  and proposes the ceiling measured x 1.05, rounded up to 1,000 bytes (the rule the budget history already uses). The
  workflow opens ONE bot pull request with the new numbers, the history reasons and the commit that moved them, so a
  feature pull request does not have to raise a budget while main has headroom. Budgets are only ever raised here;
  lowering after a real saving stays a deliberate change in the pull request that made the saving.

Covers the 8 groups in scripts/perf-budget.json (measured as check_perf_budget.py does) and the precache and
gzipped page bundle numbers in scripts/startup-budget.json (measured by check_client.mjs, which writes them when
BUDGET_MEASUREMENTS_OUT is set). Standard library only; nothing is downloaded.

Usage:
  python3 scripts/budget_drift.py [--root DIR] [--client-measurements FILE] [--cause TEXT]
                                  [--apply] [--body-out FILE]      measure, print the proposal, optionally write it
  python3 scripts/budget_drift.py --check                          the budget files are consistent (no build needed)
Exit 0: nothing to do, or the proposal was printed/applied. Exit 1: a budget file is inconsistent or input is missing.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
HEADROOM = 1.05   # new ceiling = measured x 1.05 ...
STEP = 1000       # ... rounded up to this many bytes (the rule the perf-budget history uses)

_spec = importlib.util.spec_from_file_location("check_perf_budget", HERE / "check_perf_budget.py")
assert _spec is not None and _spec.loader is not None
cpb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cpb)
WARN_RATIO = cpb.WARN_RATIO

PERF_FILE = HERE / "perf-budget.json"
STARTUP_FILE = HERE / "startup-budget.json"


def ceiling_for(measured: int) -> int:
    return math.ceil(measured * HEADROOM / STEP) * STEP


def clean_cause(text: str) -> str:
    """One short plain line; the cause comes from a commit subject, which is not trusted text."""
    one = " ".join((text or "").split())
    one = re.sub(r"[^\x20-\x7e]", "?", one)
    return (one[:160] or "main, commit not named")


def reason_for(label: str, measured: int, old: int, new: int, cause: str) -> str:
    return (f"Budget drift, raised by the budget-drift bot ({cause}). {label}: main measures {measured:,} bytes, "
            f"{measured / old * 100:.1f}% of the {old:,} byte budget; ceiling = ceil({measured:,} x {HEADROOM} / "
            f"{STEP:,}) x {STEP:,} = {new:,} ({new / measured * 100 - 100:.1f}% headroom).")


def client_targets(startup: dict, meas: dict) -> list[dict]:
    """The check_client.mjs budgets that have a measurement: [{key, label, measured, old}]."""
    out = []
    for name, label in (("install", "Service-worker install precache (raw)"), ("pack_shell", "Offline pack shell (raw)")):
        old = (startup.get("precache") or {}).get(f"{name}_raw_max")
        if isinstance(old, int) and name in (meas.get("precache") or {}):
            out.append({"key": f"precache/{name}_raw_max", "label": label, "measured": meas["precache"][name], "old": old})
    for page, budget in (startup.get("bundles") or {}).items():
        if page == "comment" or page not in (meas.get("bundles") or {}):
            continue
        for kind, word in (("js", "scripts"), ("css", "styles")):
            old = budget.get(f"{kind}_gzip_max")
            if isinstance(old, int) and kind in meas["bundles"][page]:
                out.append({"key": f"bundles/{page}/{kind}_gzip_max", "label": f"{page} initial {word} (gzipped)",
                            "measured": meas["bundles"][page][kind], "old": old})
    return out


def propose(root: Path, client_meas: dict | None, cause: str) -> list[dict]:
    """Every budget at or above WARN_RATIO of its number: {file, key, label, measured, old, new, reason}."""
    props = []
    perf = json.loads(PERF_FILE.read_text())
    for name, res in cpb.measure(root, perf).items():
        spec = perf["budgets"][name]
        old, used = spec["max_bytes"], res["bytes"]
        if used >= WARN_RATIO * old:
            new = max(ceiling_for(used), old)
            props.append({"file": "perf", "key": name, "label": spec["label"], "measured": used, "old": old, "new": new,
                          "reason": reason_for(spec["label"], used, old, new, cause)})
    if client_meas:
        for t in client_targets(json.loads(STARTUP_FILE.read_text()), client_meas):
            if t["measured"] >= WARN_RATIO * t["old"]:
                new = max(ceiling_for(t["measured"]), t["old"])
                props.append({"file": "startup", "key": t["key"], "label": t["label"], "measured": t["measured"],
                              "old": t["old"], "new": new, "reason": reason_for(t["label"], t["measured"], t["old"], new, cause)})
    return [p for p in props if p["new"] > p["old"]]


# ---- applying: perf-budget.json round-trips as indent=2 JSON; startup-budget.json is edited as text so its
# ---- hand-written layout (one-line page budgets, long comment) is untouched.

def apply_perf(props: list[dict]) -> None:
    perf = json.loads(PERF_FILE.read_text())
    for p in (x for x in props if x["file"] == "perf"):
        spec = perf["budgets"][p["key"]]
        spec["history"].append({"max_bytes": p["new"], "reason": p["reason"]})
        spec["max_bytes"] = p["new"]
    PERF_FILE.write_text(json.dumps(perf, indent=2, ensure_ascii=False) + "\n")


_HISTORY = re.compile(r'^  "drift_history": (\[.*?\])(,?)$', re.S | re.M)


def _set_number(text: str, key: str, new: int) -> str:
    """Replace the number of precache/<k> or bundles/<page>/<k> in startup-budget.json text."""
    parts = key.split("/")
    if parts[0] == "precache":
        start, leaf = text.index('"precache": {'), parts[1]
    else:
        start, leaf = text.index(f'"{parts[1]}": {{', text.index('"bundles": {')), parts[2]
    pat = re.compile(r'(?<!\\)("' + re.escape(leaf) + r'":\s*)\d+')
    m = pat.search(text, start)
    if not m:
        raise SystemExit(f"cannot find {key} in {STARTUP_FILE.name}")
    return text[:m.start()] + m.group(1) + str(new) + text[m.end():]


def apply_startup(props: list[dict]) -> None:
    mine = [x for x in props if x["file"] == "startup"]
    if not mine:
        return
    text = STARTUP_FILE.read_text()
    m = _HISTORY.search(text)
    if not m:
        raise SystemExit(f'{STARTUP_FILE.name} has no "drift_history" list')
    entries = json.loads(m.group(1))
    for p in mine:
        text = _set_number(text, p["key"], p["new"])
        entries.append({"budget": p["key"], "max_bytes": p["new"], "reason": p["reason"]})
    body = "[\n" + ",\n".join("    " + json.dumps(e, ensure_ascii=False) for e in entries) + "\n  ]"
    m = _HISTORY.search(text)
    assert m is not None
    STARTUP_FILE.write_text(text[:m.start(1)] + body + text[m.end(1):])
    json.loads(STARTUP_FILE.read_text())  # never leave an unreadable budget file behind


def body_markdown(props: list[dict], cause: str, root: Path) -> str:
    rows = "\n".join(f"| {p['label']} | `{p['key']}` | {p['measured']:,} | {p['old']:,} | {p['measured'] / p['old'] * 100:.1f}% "
                     f"| {p['new']:,} |" for p in props)
    return (f"Automatic budget drift from main ({cause}).\n\n"
            f"Each row below was at or above {WARN_RATIO:.0%} of its budget on the built main. The new number is the measured size "
            f"x {HEADROOM} rounded up to {STEP:,} bytes, and every move carries its reason in `scripts/perf-budget.json` "
            f"(`history`) or `scripts/startup-budget.json` (`drift_history`). Nothing here changes product behaviour.\n\n"
            "| Budget | Key | Measured (B) | Old (B) | Used | New (B) |\n|---|---|---:|---:|---:|---:|\n" + rows + "\n\n"
            "Opened by `.github/workflows/budget-drift.yml` running `scripts/budget_drift.py`. Review the cause above: if the growth is "
            "not worth its bytes, fix the code instead and close this pull request. Roll back by reverting this pull request.\n")


# ---- consistency check (no build needed)

def check_files() -> list[str]:
    problems = list(cpb.validate_budget(json.loads(PERF_FILE.read_text())))
    startup = json.loads(STARTUP_FILE.read_text())
    hist = startup.get("drift_history")
    if not isinstance(hist, list):
        return problems + [f'{STARTUP_FILE.name}: needs a "drift_history" list (may be empty)']
    last: dict[str, dict] = {}
    for e in hist:
        if not (isinstance(e.get("budget"), str) and isinstance(e.get("max_bytes"), int) and str(e.get("reason", "")).strip()):
            problems.append(f"drift_history entry needs budget, integer max_bytes and a reason: {e!r}")
            continue
        last[e["budget"]] = e
    for key, e in last.items():
        cur = _current(startup, key)
        if cur is None:
            problems.append(f"drift_history names {key}, which is not a budget in {STARTUP_FILE.name}")
        elif cur != e["max_bytes"]:
            problems.append(f"{key} is {cur} but its last drift_history entry says {e['max_bytes']}. To change this budget by hand, "
                            f"add a drift_history entry with the new max_bytes and a reason, and set the number to match.")
    return problems


def _current(startup: dict, key: str):
    node = startup
    for part in key.split("/"):
        node = node.get(part) if isinstance(node, dict) else None
    return node if isinstance(node, int) else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--root", type=Path, default=REPO, help="repository root with the build (dist/client)")
    ap.add_argument("--client-measurements", type=Path, help="JSON written by check_client.mjs (BUDGET_MEASUREMENTS_OUT)")
    ap.add_argument("--cause", default="", help="the commit that moved the sizes (one short line)")
    ap.add_argument("--apply", action="store_true", help="write the new numbers and their reasons into the budget files")
    ap.add_argument("--body-out", type=Path, help="write the pull request body here when there is drift")
    ap.add_argument("--check", action="store_true", help="only check that the budget files are consistent")
    args = ap.parse_args(argv)

    problems = check_files()
    if problems:
        print("BUDGET FILE PROBLEM:\n  " + "\n  ".join(problems))
        return 1
    if args.check:
        print("Budget files consistent.")
        return 0
    if not (args.root / cpb.MANIFEST).is_file():
        print(f"Build output missing ({cpb.MANIFEST}). Run `pnpm build` first.")
        return 1
    meas = json.loads(args.client_measurements.read_text()) if args.client_measurements else None
    cause = clean_cause(args.cause)
    props = propose(args.root, meas, cause)
    if not props:
        print(f"No budget drift: every measured budget is below {WARN_RATIO:.0%} of its number."
              + ("" if meas else " (Client budgets were not measured: no --client-measurements.)"))
        return 0
    for p in props:
        print(f"DRIFT {p['key']}: {p['measured']:,} B is {p['measured'] / p['old'] * 100:.1f}% of {p['old']:,}; new ceiling {p['new']:,}")
    if args.body_out:
        args.body_out.write_text(body_markdown(props, cause, args.root))
    if args.apply:
        apply_perf(props)
        apply_startup(props)
        print(f"Applied {len(props)} budget change(s). Review `git diff scripts/*budget*.json`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
