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
IGNORED = {".git", ".venv", "var", "__pycache__", ".ruff_cache", ".pytest_cache", "build", "node_modules", ".wrangler", "test-results", "playwright-report"}
PATTERNS = {
    "private home path": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/"),
    "private tailnet address": re.compile(r"\b100\.(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.\d+\.\d+\b"),
    "GitHub credential": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    "bot credential": re.compile(r"\b\d{8,}:[A-Za-z0-9_-]{30,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

# Text Advisor fixtures, plan and runbooks (docs/plans/text-advisor/02-data-model.md
# § Privacy invariants): phone numbers only from the fictional 555 series, and
# Instagram handles only from catalog/advisor/fixture-handles.json.
ADVISOR_SCOPES = ("tests/fixtures/advisor/", "docs/plans/text-advisor/")
ADVISOR_RUNBOOK = re.compile(r"docs/operations/runbooks/advisor-[^/]+\.md")
FIXTURE_HANDLES = "catalog/advisor/fixture-handles.json"
E164_NANP = re.compile(r"\+1\d{10}")
# +1555XXXXXXX (no 555 area code is assigned), or +1 NPA 555-01XX (the North
# American Numbering Plan's fictional range; other 555 lines can be real).
FICTIONAL_PHONE = re.compile(r"\+1(?:555\d{7}|\d{3}55501\d{2})")
# An @mention: not part of an email address or a path, not an npm scope (@scope/pkg, @scope-name).
MENTION = re.compile(r"(?<![\w.@/+-])@([A-Za-z0-9._]{2,30})(?![\w/-])")
HANDLE_KEYS = {"instagram", "username", "handle", "ig_handle", "ig_username", "collaborators"}
HANDLE_VALUE = re.compile(r"@?[A-Za-z0-9._]{1,30}")
FICTIONAL_HANDLE = re.compile(r"example|placeholder")


def advisor_scoped(relative):
    """True for a file the Text Advisor privacy scan covers (a repository-relative path)."""
    name = relative.as_posix()
    return name.startswith(ADVISOR_SCOPES) or bool(ADVISOR_RUNBOOK.fullmatch(name))


def load_fixture_handles(root=ROOT):
    """The allowed handles (lower case), and any problems with the list itself."""
    try:
        data = json.loads((root / FIXTURE_HANDLES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(), [f"{FIXTURE_HANDLES}: missing or not JSON"]
    allowed, problems = set(), []
    for group in ("own", "fictional", "placeholders"):
        entries = data.get(group) if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            problems.append(f"{FIXTURE_HANDLES}: '{group}' must be an object of handle -> reason")
            continue
        for handle in entries:
            if not re.fullmatch(r"[a-z0-9._]{1,30}", handle):
                problems.append(f"{FIXTURE_HANDLES}: '{group}' has an entry that is not a lower-case handle")
            elif group == "fictional" and not FICTIONAL_HANDLE.search(handle):
                problems.append(f"{FIXTURE_HANDLES}: a fictional handle must contain 'example' or 'placeholder'")
            else:
                allowed.add(handle)
    return allowed, problems


def json_handles(value, key=None):
    """Every handle-shaped string under a handle field (HANDLE_KEYS), at any depth of parsed JSON."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from json_handles(v, k)
    elif isinstance(value, list):
        for item in value:
            yield from json_handles(item, key)
    elif isinstance(value, str) and key in HANDLE_KEYS and HANDLE_VALUE.fullmatch(value):
        yield value


def advisor_privacy(relative, text, allowed):
    """Violations in one scanned file as 'path:line: rule'; never the matched number or handle."""
    errors = []

    def line(offset):
        return text.count("\n", 0, offset) + 1

    for match in E164_NANP.finditer(text):
        if not FICTIONAL_PHONE.fullmatch(match.group()):
            errors.append(f"{relative}:{line(match.start())}: phone number outside the fictional 555 series "
                          "(+1555XXXXXXX or +1NPA55501XX)")
    for match in MENTION.finditer(text):
        handle = match.group(1).rstrip(".").lower()   # a handle never ends with a period; a sentence can
        if len(handle) >= 2 and handle not in allowed:
            errors.append(f"{relative}:{line(match.start())}: Instagram handle not in {FIXTURE_HANDLES}")
    if relative.suffix == ".json":
        try:
            document = json.loads(text)
        except ValueError:
            document = None
        for value in json_handles(document):
            if value.lstrip("@").lower() not in allowed:
                errors.append(f"{relative}: handle field value not in {FIXTURE_HANDLES}")
    return errors


def main():
    errors, checked = [], 0
    handles, problems = load_fixture_handles(ROOT)
    errors.extend(problems)
    manifest = ROOT / "scripts/web-vendor-sha256.json"
    vendor_hashes = json.loads(manifest.read_text()) if manifest.exists() else {}
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if relative.parts[:2] in {("dist","client"),("dist","server")}:
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
        if advisor_scoped(relative):
            errors.extend(advisor_privacy(relative, text, handles))
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
    print(f"Checked {checked} text files: local Markdown links, release privacy rules and the Text Advisor fixture scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
