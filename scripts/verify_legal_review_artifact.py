"""Verify a cloud legal-review ZIP before using its original sources locally.

The archive is evidence, never an approval of fishing rules.  Nothing is
extracted until every expected source, identity and content hash passes.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from skippercast.pipeline.parsers import watch_content  # noqa: E402
from skippercast.pipeline.regulation_review import jurisdiction_files  # noqa: E402
from skippercast.pipeline.regulations import content_hash  # noqa: E402

MAX_ARCHIVE_BYTES = 100_000_000
MAX_MEMBER_BYTES = 40_000_000


def verify(archive, jurisdiction_id):
    jurisdiction, registry, _ = jurisdiction_files(jurisdiction_id)
    with zipfile.ZipFile(archive) as zipped:
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
        packet = json.loads(zipped.read("packet.json"))
        coverage = json.loads(zipped.read("coverage.json"))
        if packet.get("jurisdiction_id") != jurisdiction["id"] or coverage.get("jurisdiction_id") != jurisdiction["id"]:
            raise ValueError("Jurisdiction mismatch")
        if packet.get("rules_content_sha256") != content_hash(registry):
            raise ValueError("The legal registry changed after collection")
        if set(packet.get("sources", {})) != set(registry["sources"]):
            raise ValueError("Source inventory mismatch")
        verified = []
        for ident, expected in registry["sources"].items():
            record = packet["sources"][ident]
            data = record.get("data") or {}
            if record.get("status") != "ok" or record.get("url") != expected["url"]:
                raise ValueError(f"Unusable source or URL mismatch: {ident}")
            if data.get("normalization") != expected["normalization"]:
                raise ValueError(f"Normalizer mismatch: {ident}")
            kind = data["normalization"]
            if kind == "pdf-bytes-v1":
                filename = ident + ".pdf"
                body = zipped.read(filename)
                if not body.startswith(b"%PDF-"):
                    raise ValueError(f"Invalid PDF: {ident}")
                actual = hashlib.sha256(body).hexdigest()
            elif kind == "text-and-links-v3":
                filename = ident + ".html"
                actual = hashlib.sha256(watch_content(zipped.read(filename).decode("utf-8")).encode()).hexdigest()
            elif kind == "ecfr-section-text-v1":
                filename = ident + ".txt"
                text = zipped.read(filename).decode("utf-8")
                actual = hashlib.sha256(text.split("\nDOCUMENT LINKS\n", 1)[0].strip().encode()).hexdigest()
            else:
                raise ValueError(f"Unsupported source normalizer: {ident}")
            if actual != data.get("content_sha256"):
                raise ValueError(f"Source fingerprint mismatch: {ident}")
            verified.append(ident)
        return {"jurisdiction_id": jurisdiction_id, "collected_at": packet["collected_at"],
                "archive_sha256": hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
                "verified_source_count": len(verified), "source_ids": verified}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--jurisdiction", required=True)
    parser.add_argument("--output", type=Path, help="Optional review receipt JSON; source documents remain in the ZIP")
    args = parser.parse_args()
    receipt = verify(args.archive, args.jurisdiction)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
