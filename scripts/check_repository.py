"""Offline checks for local documentation links and accidental private material.

This is a small release guard, not an exhaustive secret-scanning product.
Only paths/rule names are printed on a match, never a potential secret value.
"""

from pathlib import Path
import hashlib
import json
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {".git", ".venv", "var", "__pycache__", "build", "node_modules", ".sites-runtime"}
PATTERNS = {
    "private home path": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/"),
    "private tailnet address": re.compile(r"\b100\.(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.\d+\.\d+\b"),
    "GitHub credential": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    "bot credential": re.compile(r"\b\d{8,}:[A-Za-z0-9_-]{30,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def main():
    errors, checked = [], 0
    manifest = ROOT / "scripts/web-vendor-sha256.json"
    vendor_hashes = json.loads(manifest.read_text()) if manifest.exists() else {}
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if relative.parts[:2] in {("dist","client"),("dist","server"),("dist",".openai")}:
            continue
        if not path.is_file() or set(relative.parts) & IGNORED or any(p.endswith(".egg-info") for p in relative.parts):
            continue
        if path.name in {"state.json", "config.json"} or path.suffix in {".pem", ".key"}:
            errors.append(f"{relative}: forbidden private/runtime filename")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            if vendor_hashes.get(relative.as_posix()) != hashlib.sha256(path.read_bytes()).hexdigest():
                errors.append(f"{relative}: unexpected or changed binary file requires review")
            continue
        checked += 1
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{relative}: possible {label}")
        if path.suffix == ".md":
            for raw in LINK.findall(text):
                url = urlsplit(raw.strip("<>"))
                if url.scheme or not url.path:
                    continue
                target = (path.parent / unquote(url.path)).resolve()
                if not target.is_relative_to(ROOT) or not target.exists():
                    errors.append(f"{relative}: missing or external local link {url.path}")
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Checked {checked} text files: local Markdown links and release privacy rules passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
