#!/usr/bin/env python3
"""Size budget for the first-load app files and the data files the brief reads (SC-PERF-BUDGET-1).

Why: PERF-BASELINE-1 found a 15 MB file that no test flagged. This check fails a pull request when
a measured group grows past its byte budget, and prints a plain table of every size.

How it works (offline, deterministic, no timing): it adds up file sizes in bytes. Nothing is
downloaded and nothing is timed. Two kinds of file are measured:

* First-load files: after `pnpm build`, the landing page and the app page each load one entry script, the
  scripts it imports straight away, and its stylesheets (read from dist/client/.vite/manifest.json).
  Scripts loaded later on demand (dynamic import) are not first-load and are not counted here, but the
  "largest single built file" budget still covers every file Vite emits.
* Brief data files: the committed data files the brief and the map read on every load
  (PERF-BASELINE-1 section A.8). They are measured exactly as committed, never changed.

Budgets live in scripts/perf-budget.json. To raise one in a pull request, add a new entry at the END of that
budget's "history" list with the new "max_bytes" and a "reason", and set the budget's "max_bytes" to the same
number. The check fails if "max_bytes" differs from the last history entry, so a number cannot be
changed without a written reason that reviewers see in the diff. See docs/operations/perf-budget.md.

Usage: python3 scripts/check_perf_budget.py [--root DIR] [--budget FILE]
Exit 0: every group within budget. Exit 1: a budget is exceeded or the budget file is invalid.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BUDGET = REPO / "scripts" / "perf-budget.json"
MANIFEST = Path("dist/client/.vite/manifest.json")
ASSETS = Path("dist/client/assets")


def kib(n: int) -> str:
    return f"{n / 1024:,.1f} KB"


def first_load_closure(manifest: dict, entry_key: str) -> tuple[list[str], list[str]]:
    """Files (js, css) an entry loads straight away: itself plus static imports, no dynamic imports."""
    js: list[str] = []
    css: list[str] = []
    seen: set[str] = set()
    stack = [entry_key]
    while stack:
        key = stack.pop()
        if key in seen:
            continue
        seen.add(key)
        chunk = manifest.get(key)
        if chunk is None:
            raise KeyError(f"manifest has no entry {key!r}")
        if chunk.get("file") and chunk["file"] not in js:
            js.append(chunk["file"])
        for c in chunk.get("css", []):
            if c not in css:
                css.append(c)
        stack.extend(chunk.get("imports", []))
    return sorted(js), sorted(css)


def size_of(root: Path, rel: str) -> int:
    return (root / "dist/client" / rel).stat().st_size


def measure(root: Path, budget: dict) -> dict[str, dict]:
    """name -> {"bytes": int, "files": [(path, bytes)]} for every budget group."""
    manifest = json.loads((root / MANIFEST).read_text())
    out: dict[str, dict] = {}
    for name, spec in budget["budgets"].items():
        kind = spec["kind"]
        files: list[tuple[str, int]] = []
        if kind in ("first_load_js", "first_load_css"):
            js, css = first_load_closure(manifest, spec["entry"])
            files = [(f, size_of(root, f)) for f in (js if kind == "first_load_js" else css)]
            total = sum(b for _, b in files)
        elif kind == "files":
            files = [(f, (root / f).stat().st_size) for f in spec["paths"]]
            total = sum(b for _, b in files)
        elif kind == "largest_built_file":
            files = sorted(((p.name, p.stat().st_size) for p in (root / ASSETS).iterdir() if p.is_file()),
                           key=lambda x: -x[1])
            total = files[0][1] if files else 0
            files = files[:3]
        else:
            raise ValueError(f"{name}: unknown kind {kind!r}")
        out[name] = {"bytes": total, "files": files}
    return out


def validate_budget(budget: dict) -> list[str]:
    """Problems with the budget file itself (a changed number needs a written reason)."""
    problems = []
    for name, spec in budget["budgets"].items():
        hist = spec.get("history") or []
        if not hist:
            problems.append(f"{name}: needs a non-empty history list with a reason")
            continue
        for h in hist:
            if not isinstance(h.get("max_bytes"), int) or not str(h.get("reason", "")).strip():
                problems.append(f"{name}: every history entry needs an integer max_bytes and a reason")
                break
        else:
            if spec.get("max_bytes") != hist[-1]["max_bytes"]:
                problems.append(
                    f"{name}: max_bytes {spec.get('max_bytes')} does not match the last history entry "
                    f"({hist[-1]['max_bytes']}). To change a budget, add a new history entry with the new "
                    f"max_bytes and a reason, and set max_bytes to the same number.")
    return problems


def render(budget: dict, results: dict[str, dict]) -> tuple[str, bool]:
    lines = ["SIZE BUDGET CHECK (file sizes in bytes; nothing is downloaded or timed)", ""]
    rows = []
    ok = True
    for name, spec in budget["budgets"].items():
        used, limit = results[name]["bytes"], spec["max_bytes"]
        status = "OK" if used <= limit else "OVER BUDGET"
        ok &= used <= limit
        rows.append((spec["label"], kib(used), kib(limit), f"{used / limit * 100:.0f}%", status))
    head = ("What is measured", "Size now", "Budget", "Used", "Result")
    widths = [max(len(r[i]) for r in rows + [head]) for i in range(5)]

    def fmt(r):
        return "  ".join(c.ljust(widths[i]) if i in (0, 4) else c.rjust(widths[i]) for i, c in enumerate(r))

    lines += [fmt(head), "  ".join("-" * w for w in widths)] + [fmt(r) for r in rows]
    for name, spec in budget["budgets"].items():
        res = results[name]
        if res["bytes"] > spec["max_bytes"]:
            lines += ["", f"OVER BUDGET: {spec['label']}",
                      f"  Size now {kib(res['bytes'])} ({res['bytes']:,} bytes) is over the budget of "
                      f"{kib(spec['max_bytes'])} ({spec['max_bytes']:,} bytes).",
                      "  Files, largest first:"]
            lines += [f"    {kib(b):>12}  {f}" for f, b in sorted(res["files"], key=lambda x: -x[1])[:8]]
            lines += ["  If the growth is intended, raise the budget in this pull request with a written reason:",
                      "  see docs/operations/perf-budget.md (add a history entry in scripts/perf-budget.json)."]
    lines += ["", "Not measured here: live data answers and the reef export, which are published outside this repository."]
    lines += ["", "RESULT: " + ("PASS, every group is within its budget." if ok else "FAIL, at least one group is over budget.")]
    return "\n".join(lines), ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--root", type=Path, default=REPO, help="repository root to measure")
    ap.add_argument("--budget", type=Path, default=DEFAULT_BUDGET, help="budget file")
    args = ap.parse_args(argv)
    budget = json.loads(args.budget.read_text())
    problems = validate_budget(budget)
    if problems:
        print("BUDGET FILE PROBLEM:\n  " + "\n  ".join(problems))
        return 1
    if not (args.root / MANIFEST).is_file():
        print(f"Build output missing ({MANIFEST}). Run `pnpm build` first.")
        return 1
    text, ok = render(budget, measure(args.root, budget))
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
