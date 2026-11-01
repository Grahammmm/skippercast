"""Verify a cloud legal-review ZIP before using its original sources locally.

The archive is evidence, never an approval of fishing rules.  Nothing is
extracted until every expected source, identity and content hash passes.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from skippercast.pipeline.parsers import watch_content  # noqa: E402
from skippercast.pipeline.regulation_review import jurisdiction_files  # noqa: E402
from skippercast.pipeline.regulations import content_hash  # noqa: E402

MAX_ARCHIVE_BYTES = 100_000_000
MAX_MEMBER_BYTES = 40_000_000


def _json_member(zipped, name):
    try:
        value = json.loads(zipped.read(name))
    except ValueError:
        raise ValueError(f"{name} is not valid JSON") from None
    if not isinstance(value, dict):
        raise ValueError(f"{name} is not a JSON object")
    return value


def _member(zipped, filename, text=False):
    try:
        body = zipped.read(filename)
        return body.decode("utf-8") if text else body
    except KeyError:
        raise ValueError(f"Missing source file: {filename}") from None
    except UnicodeDecodeError:
        raise ValueError(f"Unreadable text (not UTF-8): {filename}") from None


def verify(archive, jurisdiction_id):
    jurisdiction, registry, _ = jurisdiction_files(jurisdiction_id)
    try:
        zipped = zipfile.ZipFile(archive)
    except zipfile.BadZipFile:
        raise ValueError("Not a ZIP archive") from None
    with zipped:
        infos = zipped.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or any(
            item.is_dir() or item.file_size > MAX_MEMBER_BYTES
            or PurePosixPath(item.filename).is_absolute()
            or len(PurePosixPath(item.filename).parts) != 1
            or item.filename in (".", "..")
            for item in infos
        ):
            raise ValueError("Unsafe or duplicate archive member")
        if sum(item.file_size for item in infos) > MAX_ARCHIVE_BYTES:
            raise ValueError("Archive exceeds the bounded review size")
        if "packet.json" not in names or "coverage.json" not in names:
            raise ValueError("Legal review packet and coverage are required")
        packet = _json_member(zipped, "packet.json")
        coverage = _json_member(zipped, "coverage.json")
        if packet.get("jurisdiction_id") != jurisdiction["id"] or coverage.get("jurisdiction_id") != jurisdiction["id"]:
            raise ValueError("Jurisdiction mismatch")
        if packet.get("rules_content_sha256") != content_hash(registry):
            raise ValueError("The legal registry changed after collection")
        if not isinstance(packet.get("sources"), dict) or set(packet["sources"]) != set(registry["sources"]):
            raise ValueError("Source inventory mismatch")
        verified = []
        for ident, expected in registry["sources"].items():
            record = packet["sources"][ident]
            if not isinstance(record, dict):
                raise ValueError(f"Unusable source or URL mismatch: {ident}")
            data = record.get("data") if isinstance(record.get("data"), dict) else {}
            if record.get("status") != "ok" or record.get("url") != expected["url"]:
                raise ValueError(f"Unusable source or URL mismatch: {ident}")
            if data.get("normalization") != expected["normalization"]:
                raise ValueError(f"Normalizer mismatch: {ident}")
            kind = data["normalization"]
            if kind == "pdf-bytes-v1":
                filename = ident + ".pdf"
                body = _member(zipped, filename)
                if not body.startswith(b"%PDF-"):
                    raise ValueError(f"Invalid PDF: {ident}")
                actual = hashlib.sha256(body).hexdigest()
            elif kind == "text-and-links-v3":
                filename = ident + ".html"
                actual = hashlib.sha256(watch_content(_member(zipped, filename, text=True)).encode()).hexdigest()
            elif kind == "ecfr-section-text-v1":
                filename = ident + ".txt"
                text = _member(zipped, filename, text=True)
                actual = hashlib.sha256(text.split("\nDOCUMENT LINKS\n", 1)[0].strip().encode()).hexdigest()
            else:
                raise ValueError(f"Unsupported source normalizer: {ident}")
            if actual != data.get("content_sha256"):
                raise ValueError(f"Source fingerprint mismatch: {ident}")
            verified.append(ident)
        if not isinstance(packet.get("collected_at"), str) or not packet["collected_at"]:
            raise ValueError("packet.json collected_at is missing")
        return {"jurisdiction_id": jurisdiction_id, "collected_at": packet["collected_at"],
                "archive_sha256": hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
                "verified_source_count": len(verified), "source_ids": verified}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--jurisdiction", required=True)
    parser.add_argument("--output", type=Path, help="Optional review receipt JSON; source documents remain in the ZIP")
    args = parser.parse_args()
    try:
        receipt = verify(args.archive, args.jurisdiction)
    except (ValueError, OSError) as exc:
        print(f"Legal review artifact refused: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=args.output.parent, prefix=f".{args.output.name}.", suffix=".tmp")
        try:
            with os.fdopen(handle, "w") as out:
                out.write(json.dumps(receipt, indent=2) + "\n")
            os.chmod(temp, 0o644)
            os.replace(temp, args.output)
        except BaseException:
            os.unlink(temp)
            raise
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
