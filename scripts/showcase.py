#!/usr/bin/env python3
"""Before/after visual gallery of the app between two git revisions.

    python scripts/showcase.py --before <ref> --after <ref> --pages docs/showcase/pages-2026-10-31.json

For each revision this checks the commit out into a scratch git worktree, installs and builds it, serves it
with the repository's own local server, and captures every page of the pages file with the repository's
Playwright Chromium (scripts/showcase_capture.mjs) at a fixed viewport, clock, seed and set of synthetic
inputs. It then writes one self-contained HTML page (no scripts, no external styles) with a row per page:
before on the left, after on the right, the route as the heading and the merged pull requests whose files the
page loads underneath. Pixel-identical pairs (or pairs whose only differences stay within `tolerance` colour
levels, which the page then says) read "no visible change" and sort to the bottom; a page the old revision
answers with an HTTP error is shown as a new page; a page that never gives the same picture on two fresh loads
is shown as unsteady and left out of the counts. Output: <out>/showcase-<date>.html and its PNGs in
<out>/<date>/.

The pages file (JSON) carries everything specific to one repository, so the script can be reused elsewhere:
  title, timezone, now (ISO clock both revisions see), seed, tolerance, pr_url, how_chosen, setup (stub module,
  see showcase_capture.mjs), local_storage / session_storage, install / build (argv lists), serve {cmd, env,
  health, port, timeout}, binary_manifest (optional JSON of path -> sha256 to pin the PNGs in), not_shown (PRs
  the gallery cannot show, with the reason), and pages: [{id, route, path, viewport, viewport_label?, full_page?,
  paths (globs of the files the page loads), prs?, note?, ...capture options}].
Only the local server is captured; the capture blocks every other origin.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import html
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "scripts/showcase_capture.mjs"
MERGE_SUBJECT = re.compile(r"^Merge pull request #(\d+)\b")
SQUASH_SUBJECT = re.compile(r"^(.*) \(#(\d+)\)$")


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def merged_prs(before: str, after: str, cwd: Path = ROOT) -> list[dict]:
    """The pull requests merged on the first-parent line in before..after, oldest first, with the files each changed."""
    out = git("log", "--first-parent", "--reverse", "--format=%H%x1f%s%x1f%b%x1e", f"{before}..{after}", cwd=cwd)
    rows = []
    for record in out.split("\x1e"):
        if not record.strip():
            continue
        sha, subject, body = (record.strip("\n").split("\x1f") + ["", ""])[:3]
        merge, squash = MERGE_SUBJECT.match(subject), SQUASH_SUBJECT.match(subject)
        if merge:
            number, title = int(merge.group(1)), (body.strip().splitlines() or [subject])[0].strip()
        elif squash:
            number, title = int(squash.group(2)), squash.group(1).strip()
        else:
            number, title = None, subject.strip()
        files = git("diff", "--name-only", f"{sha}^1", sha, cwd=cwd).split()
        rows.append({"sha": sha, "number": number, "title": title, "files": files})
    return rows


def prs_for_page(page: dict, prs: list[dict]) -> list[dict]:
    """The merged PRs that changed a file the page loads (its `paths` globs), plus any it names in `prs`."""
    globs, named = page.get("paths", []), set(page.get("prs", []))
    return [pr for pr in prs if pr["number"] in named or any(fnmatch.fnmatch(f, g) for f in pr["files"] for g in globs)]


def run(cmd: list[str], cwd: Path, log, env: dict | None = None) -> None:
    log.write(f"$ {' '.join(cmd)}\n")
    log.flush()
    subprocess.run(cmd, cwd=cwd, check=True, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, **(env or {})})


def wait_healthy(url: str, server: subprocess.Popen, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"the server exited ({server.returncode}) before {url} answered")
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1)
    raise RuntimeError(f"{url} did not answer within {timeout:.0f} s")


def stop(server: subprocess.Popen) -> None:
    if server.poll() is not None:
        return
    os.killpg(server.pid, signal.SIGTERM)
    try:
        server.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(server.pid, signal.SIGKILL)
        server.wait(timeout=30)


def capture_revision(sha: str, label: str, config: dict, work: Path, log, reuse: bool = False) -> dict:
    """Check out, build, serve and capture one revision; returns {page id: result} (result["png"] is the screenshot)."""
    out = work / label
    load = lambda: {row["id"]: {**row, "png": str(out / f"{row['id']}.png")} for row in json.loads((out / "results.json").read_text())}
    if reuse and (out / "results.json").exists():
        return load()
    tree = work / f"tree-{sha[:12]}"
    if not tree.exists():
        run(["git", "worktree", "add", "--detach", str(tree), sha], ROOT, log)
    for step in config.get("install", []) + config.get("build", []):
        run(step, tree, log)
    serve = config["serve"]
    port = str(serve.get("port", 8791))
    env = {k: v.replace("{port}", port) for k, v in serve.get("env", {}).items()}
    base = f"http://localhost:{port}"
    log.write(f"$ {' '.join(serve['cmd'])} (port {port})\n")
    log.flush()
    server = subprocess.Popen(serve["cmd"], cwd=tree, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, **env}, start_new_session=True)
    try:
        wait_healthy(base + serve.get("health", "/"), server, serve.get("timeout", 180))
        job = {k: config[k] for k in ("now", "seed", "setup", "timezone", "color_scheme", "local_storage", "session_storage", "tolerance") if k in config}
        job.update(base_url=base, out_dir=str(out), root=str(tree), pages=config["pages"])
        job_file = work / f"{label}.json"
        job_file.write_text(json.dumps(job, indent=1))
        run(["node", str(CAPTURE), str(job_file)], ROOT, log)
    finally:
        stop(server)
    return load()


def compare(pairs: list[dict], work: Path, log, tolerance: int = 0) -> dict:
    """Pixel comparison in the browser (no image library needed): {id: {changed, exact, total, box}}."""
    work.mkdir(parents=True, exist_ok=True)
    job = work / "compare.json"
    job.write_text(json.dumps({"compare": pairs, "out": str(work / "compare-results.json"), "tolerance": tolerance}))
    run(["node", str(CAPTURE), str(job)], ROOT, log)
    return {row["id"]: row for row in json.loads((work / "compare-results.json").read_text())}


def classify(before: dict | None, after: dict | None, diff: dict | None, unstable: bool) -> str:
    if not after or after["status"] != "ok":
        return "failed"
    if unstable:
        return "unstable"
    if not before or before["status"] == "missing":
        return "new"
    if before["status"] != "ok":
        return "failed-before"
    return "changed" if diff and diff["changed"] else "same"


ORDER = {"changed": 0, "new": 1, "failed-before": 2, "failed": 3, "unstable": 4, "same": 5}
BADGE = {"changed": "Visible change", "new": "New page", "same": "No visible change", "failed": "Did not render now",
         "failed-before": "Did not render before", "unstable": "Unsteady capture"}


def where(box: dict, width: int, height: int) -> str:
    """Plain words for where on the screen a change box sits."""
    cx, cy = (box["x"] + box["w"] / 2) / width, (box["y"] + box["h"] / 2) / height
    if box["w"] * box["h"] > 0.6 * width * height:
        return "across most of the screen"
    vertical = "top" if cy < 1 / 3 else "bottom" if cy > 2 / 3 else "middle"
    horizontal = "left" if cx < 1 / 3 else "right" if cx > 2 / 3 else ""
    return f"in the {vertical}{' ' + horizontal if horizontal else ''} of the screen"


def areas(diff: dict, gap: int = 2, keep: int = 6) -> list[dict]:
    """Separate changed areas: the changed cells joined when within `gap` cells of each other, largest first."""
    cols, size, cells = diff["cols"], diff["cell"], set(diff["cells"])
    seen, boxes = set(), []
    for start in sorted(cells):
        if start in seen:
            continue
        seen.add(start)
        stack, members = [start], []
        while stack:
            cell = stack.pop()
            members.append(cell)
            r, c = divmod(cell, cols)
            for dr in range(-gap, gap + 1):
                for dc in range(-gap, gap + 1):
                    n = (r + dr) * cols + (c + dc)
                    if 0 <= c + dc < cols and n in cells and n not in seen:
                        seen.add(n)
                        stack.append(n)
        rows_, cols_ = [m // cols for m in members], [m % cols for m in members]
        x, y = min(cols_) * size, min(rows_) * size
        boxes.append({"x": x, "y": y, "w": min((max(cols_) + 1) * size, diff["width"]) - x, "h": min((max(rows_) + 1) * size, diff["height"]) - y})
    return sorted(boxes, key=lambda b: -b["w"] * b["h"])[:keep]


def short(sha: str) -> str:
    return sha[:9]


def png_size(path: Path) -> tuple[int, int]:
    """Width and height from a PNG's IHDR chunk."""
    head = path.read_bytes()[:24]
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def local_time(iso: str, zone: str) -> str:
    return dt.datetime.fromisoformat(iso).astimezone(ZoneInfo(zone)).strftime("%Y-%m-%d %H:%M %Z")


def render(rows: list[dict], meta: dict, unshown: list[dict], others: list[dict]) -> str:
    """The gallery page: inline styles only, readable with images off and on a phone."""
    e = html.escape
    rows = sorted(rows, key=lambda r: (ORDER[r["kind"]], -r.get("fraction", 0), r["index"]))
    counts = {kind: sum(r["kind"] == kind for r in rows) for kind in ORDER}
    pr_link = lambda pr: (f'<a href="{e(meta["pr_url"].format(n=pr["number"]))}">#{pr["number"]}</a> ' if pr["number"] and meta.get("pr_url") else
                          f"#{pr['number']} " if pr["number"] else "") + e(pr["title"])
    out = [f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(meta['title'])}: before and after, {e(meta['date'])}</title>
<style>
:root{{color-scheme:light dark;--bg:#0d1620;--card:#152230;--text:#e8eef4;--muted:#9fb0c0;--line:#2a3a4c;--change:#ffb02e;--same:#6fcf97;--new:#62b6ff;--bad:#ff7b7b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:16px}}h1{{font-size:1.6rem;line-height:1.2;margin:.4em 0}}h2{{font-size:1.15rem;margin:0;word-break:break-all}}
a{{color:#8cc8ff}}code{{font-size:.9em}}.lede,.muted{{color:var(--muted)}}
.summary{{display:flex;flex-wrap:wrap;gap:8px;padding:0;list-style:none}}.summary li{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 10px}}
.pair{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:18px 0}}
.head{{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:baseline}}
.badge{{font-size:.8rem;font-weight:700;border-radius:99px;padding:2px 10px;border:1px solid currentColor}}
.changed .badge{{color:var(--change)}}.same .badge{{color:var(--same)}}.new .badge{{color:var(--new)}}.failed .badge,.failed-before .badge,.unstable .badge{{color:var(--bad)}}
.why{{margin:6px 0}}.prs{{margin:6px 0 10px;padding-left:1.2em;font-size:.92rem}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:10px;align-items:start}}
.landscape .cols{{grid-template-columns:1fr}}@media(min-width:900px){{.landscape .cols{{grid-template-columns:1fr 1fr}}}}
figure{{margin:0}}figcaption{{font-size:.85rem;color:var(--muted);margin-bottom:4px}}
.shot{{position:relative;background:#22313f;border-radius:6px;overflow:hidden}}
.shot img{{display:block;width:100%;height:auto;color:var(--muted);font-size:.85rem}}
.box{{position:absolute;outline:3px solid var(--change);outline-offset:1px;border-radius:3px;pointer-events:none}}
.empty{{display:flex;align-items:center;justify-content:center;text-align:center;padding:16px;color:var(--muted);border:2px dashed var(--line);border-radius:6px;min-height:160px}}
details{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:18px 0}}summary{{cursor:pointer;font-weight:600}}
</style></head><body><main>
<h1>{e(meta['title'])}: what changed on screen, {e(meta['date'])}</h1>
<p class="lede">Left: <b>before</b>, <code>{short(meta['before'])}</code> ({e(meta['before_date'])}). Right: <b>after</b>, <code>{short(meta['after'])}</code> ({e(meta['after_date'])}).
{len(meta['prs'])} pull requests were merged between them. Pages with a visible change come first; pages that look exactly the same are at the bottom.
Orange outlines mark the areas that changed.</p>
<ul class="summary"><li><b>{counts['changed']}</b> {'page' if counts['changed'] == 1 else 'pages'} changed</li><li><b>{counts['new']}</b> new {'page' if counts['new'] == 1 else 'pages'}</li><li><b>{counts['same']}</b> no visible change</li>"""]
    if counts["failed"] + counts["failed-before"] + counts["unstable"]:
        out.append(f"<li><b>{counts['failed'] + counts['failed-before'] + counts['unstable']}</b> could not be compared</li>")
    out.append(f"""</ul>
<details><summary>How these screenshots were taken</summary><p>Both revisions were built from a clean checkout and served locally, then opened in the same Chromium at the same
viewport, theme, time zone and random seed, with the clock fixed at {e(meta['now_text'])}. Forecasts, buoys, tides and map imagery are synthetic stand-ins and every
outside service is blocked, so the only difference between the columns is the code. Each screenshot was kept only once two frames in a row matched{e(meta['stable_text'])}.
{e(meta['tolerance_text'])}</p></details>""")
    if meta.get("how_chosen"):
        out.append(f"<details><summary>How these pages were chosen</summary><p>{e(meta['how_chosen'])}</p></details>")
    for r in rows:
        page, w, h = r["page"], r["width"], r["height"]
        cls = f"pair {r['kind']}{' landscape' if w > h else ''}"
        out.append(f'<section class="{cls}" id="{e(page["id"])}"><div class="head"><h2>{e(page["route"])}</h2><span class="badge">{BADGE[r["kind"]]}</span>'
                   f'<span class="muted">{e(page.get("viewport_label", ""))} {w}×{h}</span></div>')
        if page.get("note"):
            out.append(f'<p class="why">{e(page["note"])}</p>')
        out.append(f'<p class="why">{e(r["summary"])}</p>')
        if r["prs"]:
            out.append('<ul class="prs">' + "".join(f"<li>{pr_link(pr)}</li>" for pr in r["prs"]) + "</ul>")
        else:
            out.append('<p class="muted">No pull request merged in this range changed a file this page loads.</p>')
        boxes = "".join(f'<span class="box" style="left:{b["x"] / w:.2%};top:{b["y"] / h:.2%};width:{b["w"] / w:.2%};height:{b["h"] / h:.2%}"></span>'
                        for b in r.get("boxes", []))
        boxed = r.get("before_size") == r.get("after_size")
        out.append('<div class="cols">')
        for side, label, sha in (("before", "Before", meta["before"]), ("after", "After", meta["after"])):
            src = r.get(f"{side}_src")
            out.append(f"<figure><figcaption>{label} · <code>{short(sha)}</code></figcaption>")
            if src:
                sw, sh = r.get(f"{side}_size") or (w, h)
                alt = f"{label}: {page['route']} at {sw}×{sh}"
                out.append(f'<div class="shot"><img src="{e(src)}" width="{sw}" height="{sh}" loading="lazy" decoding="async" alt="{e(alt)}">'
                           f'{boxes if boxed or side == "after" else ""}</div>')
            else:
                out.append(f'<div class="empty">{e(r.get(f"{side}_empty", "No screenshot"))}</div>')
            out.append("</figure>")
        out.append("</div></section>")
    if unshown:
        out.append(f"<details open><summary>Changes this gallery cannot show ({sum(len(u['prs']) for u in unshown)} pull requests)</summary>")
        for u in unshown:
            out.append(f'<p>{e(u["reason"])}</p><ul class="prs">' + "".join(f"<li>{pr_link(pr)}</li>" for pr in u["prs"]) + "</ul>")
        out.append("</details>")
    if others:
        out.append(f"<details><summary>Merged pull requests with nothing on screen to show ({len(others)})</summary>"
                   "<p class=\"muted\">None of the files these changed is loaded by a page above: tests, CI, data pipelines, server-only code and documents.</p>"
                   '<ul class="prs">' + "".join(f"<li>{pr_link(pr)}</li>" for pr in others) + "</ul></details>")
    out.append(f'<p class="muted">Made by <code>scripts/showcase.py</code> from <code>{e(meta["pages_file"])}</code>. To redo it: '
               f'<code>python scripts/showcase.py --before {short(meta["before"])} --after {short(meta["after"])} --pages {e(meta["pages_file"])}</code>.</p>')
    out.append("</main></body></html>\n")
    return "\n".join(out)


def summary_for(kind: str, page: dict, before: dict | None, after: dict | None, diff: dict | None, before_sha: str, tolerance: int = 0) -> str:
    if kind == "changed":
        pct = diff["changed"] / diff["total"]
        return f"{diff['changed']:,} pixels differ ({pct:.1%} of the screenshot), {where(diff['box'], diff['width'], diff['height'])}."
    if kind == "same":
        if diff and diff.get("exact"):
            return (f"No visible change: {diff['exact']:,} pixels differ by at most {tolerance} colour levels out of 255 "
                    "(anti-aliasing noise at edges, invisible to the eye).")
        return "No visible change: the two screenshots are identical, pixel for pixel."
    if kind == "new":
        status = before.get("http_status") if before else None
        return f"New page: {page['path']} did not exist at {short(before_sha)}" + (f" (it answered HTTP {status})." if status else ".")
    if kind == "unstable":
        return "Two captures of the same revision differed, so this pair cannot be compared fairly; it is left out of the counts."
    if kind == "failed-before":
        return f"The page did not render at {short(before_sha)}: {(before or {}).get('error') or 'no screenshot'}."
    return f"The page did not render at the new revision: {(after or {}).get('error') or 'no screenshot'}."


def pin_binaries(manifest: Path, files: list[Path], out_dir: Path) -> None:
    """Record each PNG's SHA-256 in the repository's binary manifest, dropping stale entries for out_dir."""
    pins = json.loads(manifest.read_text())
    prefix = out_dir.relative_to(ROOT).as_posix() + "/"
    pins = {k: v for k, v in pins.items() if not k.startswith(prefix)}
    for f in files:
        pins[f.relative_to(ROOT).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(dict(sorted(pins.items())), indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--before", required=True, help="git ref of the left column")
    parser.add_argument("--after", required=True, help="git ref of the right column")
    parser.add_argument("--pages", required=True, type=Path, help="pages file (JSON, see the module docstring)")
    parser.add_argument("--out", type=Path, default=ROOT / "docs/showcase", help="output directory (default docs/showcase)")
    parser.add_argument("--date", help="date in the file names (default: the after commit's date in the pages file's time zone)")
    parser.add_argument("--work", type=Path, help="scratch directory for worktrees and raw captures (default: a new temporary directory)")
    parser.add_argument("--keep", action="store_true", help="keep the scratch worktrees and raw captures")
    parser.add_argument("--reuse", action="store_true", help="with --work: reuse captures already in it (re-render the page only)")
    args = parser.parse_args(argv)

    config = json.loads(args.pages.read_text())
    if not (ROOT / "node_modules/@playwright/test").exists():
        print("Install the repository's dev dependencies first (pnpm install): scripts/showcase_capture.mjs uses @playwright/test.", file=sys.stderr)
        return 2
    before, after = (git("rev-parse", "--verify", f"{ref}^{{commit}}").strip() for ref in (args.before, args.after))
    zone = config.get("timezone", "UTC")
    stamp = lambda sha: git("show", "-s", "--format=%cI", sha).strip()
    local = lambda iso: local_time(iso, zone)
    date = args.date or local(stamp(after))[:10]
    out_dir = args.out.resolve()
    shots_dir = out_dir / date
    prs = merged_prs(before, after)

    work = (args.work or Path(tempfile.mkdtemp(prefix="showcase-"))).resolve()
    work.mkdir(parents=True, exist_ok=True)
    log_path = work / "showcase.log"
    print(f"before {short(before)}  after {short(after)}  {len(prs)} merged PRs  scratch {work}  log {log_path}")
    captured: dict[str, dict] = {}
    tolerance = int(config.get("tolerance", 0))
    with log_path.open("a") as log:
        for label, sha in (("before", before), ("after", after)):
            print(f"{label}: building and capturing {short(sha)} ...", flush=True)
            try:
                captured[label] = capture_revision(sha, label, config, work, log, reuse=args.reuse)
            except (subprocess.CalledProcessError, RuntimeError) as error:
                print(f"{label}: {error} (see {log_path})", file=sys.stderr)
                # Every page of a revision that did not build or serve failed; none of them is a "new page".
                captured[label] = {p["id"]: {"status": "failed", "error": f"the {label} revision did not build or serve"} for p in config["pages"]}
        pairs = []
        for page in config["pages"]:
            b, a = captured["before"].get(page["id"]), captured["after"].get(page["id"])
            if a and a["status"] == "ok" and b and b["status"] == "ok":
                pairs.append({"id": page["id"], "before": b["png"], "after": a["png"]})
        diffs = compare(pairs, work / "pairs", log, tolerance) if pairs else {}

    shots_dir.mkdir(parents=True, exist_ok=True)
    for old in shots_dir.glob("*.png"):   # this run's output replaces the last one's
        old.unlink()
    rows, written = [], []
    for index, page in enumerate(config["pages"]):
        b, a = captured["before"].get(page["id"]), captured["after"].get(page["id"])
        diff = diffs.get(page["id"])
        # Fair only when each side gave the same picture on two fresh loads (showcase_capture.mjs).
        unstable = any(res and res["status"] == "ok" and not res.get("steady") for res in (b, a))
        kind = classify(b, a, diff, unstable)
        vp = (a or b or {}).get("viewport") or {"width": 390, "height": 844}
        width, height = (diff["width"], diff["height"]) if diff else (vp["width"], vp["height"])
        row = {"page": page, "kind": kind, "index": index, "width": width, "height": height,
               "prs": prs_for_page(page, prs), "summary": summary_for(kind, page, b, a, diff, before, tolerance)}
        if diff and diff["changed"]:
            row["fraction"], row["box"] = diff["changed"] / diff["total"], diff["box"]
            # Outlines help only when the change is local; a moved map changes most of the screen.
            if diff["box"]["w"] * diff["box"]["h"] <= 0.6 * diff["width"] * diff["height"]:
                row["boxes"] = areas(diff)
            elif row["fraction"] < 0.3:
                row["boxes"] = [b for b in areas(diff) if b["w"] * b["h"] <= 0.6 * diff["width"] * diff["height"]]
        shared = kind == "same" and diff is not None and diff["exact"] == 0
        for side, res in (("before", b), ("after", a)):
            if res and res["status"] == "ok" and Path(res["png"]).exists():
                # A pixel-identical pair shares one file; otherwise each side has its own.
                name = f"{page['id']}.png" if shared else f"{page['id']}-{side}.png"
                target = shots_dir / name
                if not (shared and side == "after"):
                    shutil.copyfile(res["png"], target)
                    written.append(target)
                row[f"{side}_src"] = f"{date}/{name}"
                row[f"{side}_size"] = png_size(Path(res["png"]))
        if kind == "new":
            row.pop("before_src", None)
            row["before_empty"] = f"New page: not in {short(before)}"
        elif not row.get("before_src"):
            row["before_empty"] = "Did not render"
        if not row.get("after_src"):
            row["after_empty"] = "Did not render"
        rows.append(row)

    shown = {pr["sha"] for r in rows for pr in r["prs"]}
    unshown = []
    for item in config.get("not_shown", []):
        listed = [pr for pr in prs if pr["number"] in set(item["prs"]) and pr["sha"] not in shown]
        if listed:
            unshown.append({"reason": item["reason"], "prs": listed})
            shown |= {pr["sha"] for pr in listed}
    others = [pr for pr in prs if pr["sha"] not in shown]
    meta = {"title": config.get("title", ROOT.name), "date": date, "before": before, "after": after, "how_chosen": config.get("how_chosen"),
            "before_date": local(stamp(before)), "after_date": local(stamp(after)), "prs": prs, "pr_url": config.get("pr_url"),
            "now_text": local(config["now"]) if config.get("now") else "the capture time",
            "stable_text": ", and each page was loaded afresh until two loads in a row gave the same picture",
            "tolerance_text": (f"A pixel counts as changed when a colour channel moves by more than {tolerance} levels out of 255; smaller moves are "
                               "anti-aliasing noise that can differ even between two captures of one revision. " if tolerance else ""),
            "pages_file": args.pages.resolve().relative_to(ROOT).as_posix() if args.pages.resolve().is_relative_to(ROOT) else args.pages.name}
    page_path = out_dir / f"showcase-{date}.html"
    page_path.write_text(render(rows, meta, unshown, others))
    if config.get("binary_manifest"):
        pin_binaries(ROOT / config["binary_manifest"], sorted(written), shots_dir)
    tally = {kind: sum(r["kind"] == kind for r in rows) for kind in ORDER}
    print(f"wrote {page_path.relative_to(ROOT) if page_path.is_relative_to(ROOT) else page_path}: "
          f"{tally['changed']} visible change, {tally['new']} new, {tally['same']} no visible change, "
          f"{tally['failed'] + tally['failed-before'] + tally['unstable']} not comparable")
    if not args.keep:
        for label in ("before", "after"):
            sha = before if label == "before" else after
            tree = work / f"tree-{sha[:12]}"
            if tree.exists():
                subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=ROOT, capture_output=True)
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
