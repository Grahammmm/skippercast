#!/usr/bin/env python3
"""PR-tier guard for the reviewed-source hash pins that only the main-only e2e job checks.

e2e/*.spec.ts files bind exact sha256 hashes of the source files they were reviewed against
(`REVIEWED_SOURCE_INPUTS`, e.g. BODY09 in p04-catch-contrast.spec.ts). e2e runs only on main
(R12 fast PR tier), so a PR that changed a pinned file without re-pinning it merged green and
turned main red (W10B #1043 -> BODY09, 2026-10-29). This check runs on every PR in seconds: each
pinned file must hash to its pin. A PR that changes a pinned file must re-pin it in the same PR,
which sends the change through applicability review.

Usage: python3 scripts/check_e2e_pins.py   (exit 1 lists every mismatch)
"""
import glob
import hashlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCK = re.compile(r"const REVIEWED_SOURCE_INPUTS[^=]*=\s*\{(.*?)\n\};", re.S)
ENTRY = re.compile(r'"([^"\n]+)"\s*:\s*"([0-9a-f]{64})"')


def pins():
    """[(spec, path, sha256)] for every REVIEWED_SOURCE_INPUTS block under e2e/."""
    out = []
    for spec in sorted(glob.glob(os.path.join(ROOT, "e2e", "*.spec.ts"))):
        text = open(spec, encoding="utf-8").read()
        for block in BLOCK.findall(text):
            out += [(os.path.relpath(spec, ROOT), p, h) for p, h in ENTRY.findall(block)]
    return out


def main():
    found = pins()
    if not found:
        print("e2e pin guard: no REVIEWED_SOURCE_INPUTS pins found (pattern changed?)")
        return 1
    bad = []
    for spec, path, want in found:
        full = os.path.join(ROOT, path)
        got = hashlib.sha256(open(full, "rb").read()).hexdigest() if os.path.isfile(full) else "missing"
        if got != want:
            bad.append(f"{path}: pinned in {spec} as {want[:12]}, now {got[:12]}")
    if bad:
        print("e2e pin guard: changed files are pinned by a main-only e2e check. Re-pin them in this PR "
              "(with an applicability note) or revert the change:")
        print("\n".join("  " + b for b in bad))
        return 1
    print(f"e2e pin guard: {len(found)} pinned files match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
