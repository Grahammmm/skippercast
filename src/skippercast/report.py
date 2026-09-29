"""Render run manifests as a GitHub step-summary Markdown table.

    python -m skippercast.report var/runs/forecast-build.json >> "$GITHUB_STEP_SUMMARY"
    python -m skippercast.report --append-summary var/runs/*.json

With --append-summary the Markdown is appended to $GITHUB_STEP_SUMMARY (and
still printed). Exit status is 0 when every manifest was read, whatever the run
status; the job's own exit code decides whether the workflow fails. This is the
shared replacement for the per-workflow heredoc reporters.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from .platform.contracts import read_json
from .runs import validate

MARK = {"ok": "✅ ok", "degraded": "⚠️ degraded", "failed": "❌ failed"}
DETAIL_KEYS = ("detail", "error_class", "http_status", "region", "issue")


def cell(value):
    """A single-line, pipe-safe Markdown table cell."""
    if value is None or value == "":
        return "–"
    text = " ".join(str(value).split())
    return text.replace("\\", "\\\\").replace("|", "\\|")[:300]


def seconds(ms):
    return "–" if ms is None else f"{ms / 1000:.1f} s"


def render(manifest):
    """Markdown for one manifest."""
    m = validate(manifest)
    status = m.get("status")
    lines = [f"### {cell(m['job'])}: {MARK.get(status, cell(status))}", ""]
    run = cell(m["run_id"]) + (f" (attempt {m['run_attempt']})" if m.get("run_attempt") else "")
    sha = (m.get("git_sha") or "")[:12]
    lines += ["| Run | Commit | Started | Duration | Exit |", "| --- | --- | --- | --- | --- |",
              f"| {run} | {cell(sha)} | {cell(m['started_at'])} | {seconds(m.get('duration_ms'))} | {cell(m.get('exit_code'))} |", ""]
    if m.get("error"):
        lines += [f"**Error:** `{cell(m['error'].get('class'))}` {cell(m['error'].get('message'))}", ""]
    if m["sources"]:
        lines += ["| Source | Status | Duration | Detail |", "| --- | --- | --- | --- |"]
        for ident, row in sorted(m["sources"].items(), key=lambda item: (item[1]["status"] == "ok", item[0])):
            detail = "; ".join(f"{k}: {row[k]}" if k != "detail" else str(row[k]) for k in DETAIL_KEYS if row.get(k) not in (None, ""))
            lines.append(f"| {cell(ident)} | {MARK.get(row['status'], cell(row['status']))} | {seconds(row.get('duration_ms'))} | {cell(detail)} |")
        counts = {}
        for row in m["sources"].values():
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        lines += ["", "Sources: " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())), ""]
    for title, files in (("Inputs", m["inputs"]), ("Outputs", m["outputs"])):
        if files:
            lines += [f"<details><summary>{title} ({len(files)})</summary>", "",
                      "| File | Bytes | sha256 |", "| --- | ---: | --- |"]
            lines += [f"| {cell(f.get('path'))} | {f.get('bytes', '–')} | `{cell((f.get('sha256') or '')[:12])}` |" for f in files]
            lines += ["", "</details>", ""]
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="skippercast.report", description=__doc__.splitlines()[0])
    parser.add_argument("manifests", nargs="+", type=Path)
    parser.add_argument("--append-summary", action="store_true",
                        help="also append to the file named by $GITHUB_STEP_SUMMARY")
    args = parser.parse_args(argv)
    parts, status = [], 0
    for path in args.manifests:
        try:
            parts.append(render(read_json(path)))
        except (OSError, ValueError) as error:
            print(f"{path}: {type(error).__name__}: {error}", file=sys.stderr)
            status = 1
    text = "\n".join(parts)
    sys.stdout.write(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if args.append_summary and summary and text:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return status


if __name__ == "__main__":
    sys.exit(main())
