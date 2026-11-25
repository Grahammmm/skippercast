#!/usr/bin/env python3
"""Render a self-contained local ballot from an independently pinned M28 manifest.

Give the judge only the resulting HTML. Its JSON download is input for the
existing tally, never an R8 verdict. No blind key is needed or disclosed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import itertools
import json
import re
from pathlib import Path

CAMERAS = {"GAP": "gap", "LABEL": "harbor"}
CHOICES = {"GAP": ("yes", "no", "cannot-tell"),
           "LABEL": ("yes", "no", "no-lines-visible", "cannot-tell")}
VIEWS = set(itertools.product(CAMERAS, ("light", "dark"), (11, 13, 15)))

PAGE = '''<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Morro phone-view ballot</title>
<style>
body{font:16px system-ui;margin:8px} section{border-top:1px solid;padding-block:8px}
.pair{display:flex;gap:16px;flex-wrap:wrap} figure{margin:0 0 12px;min-width:0}
.photo{max-width:calc(100vw - 16px);overflow-x:auto} img{display:block;width:390px;height:auto}
select,input,button{font:inherit;min-height:44px} output{display:block}
</style>
<h1>Morro phone-view ballot</h1>
<p>Local views only. Not hosted, not a release review or approval.</p>
<p>View at normal size. Scroll a picture sideways if your screen is narrower than 390 px.
Answer A and B separately. Leave unexamined views as Unjudged; choose Cannot tell if you looked but could not decide.</p>
<label>Judge identifier <input id="judge" autocomplete="off"></label>
<p>Manifest <code id="manifest">@PIN@</code></p>
@VIEWS@
<button id="download" type="button">Download answers JSON</button>
<output id="status" aria-live="polite"></output>
<script>
const byId = (id) => document.getElementById(id);
byId('download').addEventListener('click', () => {
  const judge = byId('judge').value.trim() || null;
  const answers = Object.create(null);
  for (const element of document.querySelectorAll('select[data-side]')) {
    const row = answers[element.dataset.pair] ??= {A: null, B: null, note: null};
    row[element.dataset.side] = judge ? element.value || null : null;
  }
  const receipt = {schema: 'sc-morro-blind-answers/1',
    manifest_sha256: byId('manifest').textContent, judge, answers};
  const url = URL.createObjectURL(new Blob([JSON.stringify(receipt, null, 2) + '\\n'],
    {type: 'application/json'}));
  const link = document.createElement('a');
  link.download = 'morro-answers.json';
  link.href = url;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  byId('status').textContent = judge ? 'Answers downloaded.' : 'No judge named; all views exported as unjudged.';
});
</script>
'''


def render(manifest: Path, expected: str) -> str:
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("manifest does not match the independently supplied SHA-256")
    payload = json.loads(raw)
    if payload["schema"] != "sc-morro-blind-pairs/1" or not re.fullmatch(r"[a-f0-9]{64}", payload["key_sha256"]):
        raise ValueError("not a bound M28 manifest")
    if manifest.parent.joinpath("images").is_symlink():
        raise ValueError("images directory must not be a symlink")
    views, ids, sections = set(), set(), []
    for row in payload["pairs"]:
        pid, question, theme, zoom = (row[k] for k in ("pair", "question", "theme", "zoom"))
        view = (question, theme, zoom)
        if (not re.fullmatch(r"pair-\d{2}", pid) or pid in ids or view in views
                or view not in VIEWS or row["camera"] != CAMERAS[question]
                or set(row["images"]) != {"A", "B"}):
            raise ValueError(f"invalid or repeated view: {pid}")
        ids.add(pid)
        views.add(view)
        prompt = payload["questions"][question]
        if tuple(prompt["allowed"]) != CHOICES[question] or prompt["camera"] != row["camera"]:
            raise ValueError(f"unexpected question contract: {question}")
        title = f"{pid}: {question} · {theme} · {row['camera']} · z{zoom}"
        section = [f"<section><h2>{title}</h2><p>{html.escape(prompt['text'])}</p><div class=pair>"]
        options = '<option value="">Unjudged</option>' + ''.join(
            f'<option value="{choice}">{choice.replace("-", " ").capitalize()}</option>'
            for choice in CHOICES[question])
        for side in ("A", "B"):
            photo = row["images"][side]
            filename = f"images/{pid}-{side}.png"
            path = manifest.parent / filename
            if photo["file"] != filename or path.is_symlink():
                raise ValueError(f"unexpected picture path: {pid}/{side}")
            content = path.read_bytes()
            if not content.startswith(b"\x89PNG\r\n\x1a\n") or hashlib.sha256(content).hexdigest() != photo["sha256"]:
                raise ValueError(f"picture does not match manifest: {pid}/{side}")
            data = base64.b64encode(content).decode("ascii")
            section.append(f'<figure><div class=photo><img alt="{pid} picture {side}" '
                           f'src="data:image/png;base64,{data}"></div><figcaption><label>{side} '
                           f'<select data-pair="{pid}" data-side="{side}">{options}</select>'
                           '</label></figcaption></figure>')
        sections.append(''.join(section) + '</div></section>')
    if views != VIEWS:
        raise ValueError("manifest must contain all 12 distinct M28 views")
    return PAGE.replace("@PIN@", expected).replace("@VIEWS@", '\n'.join(sections))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path, help="new HTML file (must not already exist)")
    args = parser.parse_args()
    try:
        page = render(args.manifest, args.manifest_sha256)
        with args.output.open("x", encoding="utf-8") as out:
            out.write(page)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"Ballot refused; no views judged: {exc}\n")
    print(f"Local ballot: {args.output} (12 pairs, 24 initially unjudged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
