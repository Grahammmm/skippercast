"""python -m skippercast.pipeline --output var/daily --previous var/previous.json"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from .collect import collect, validate
from .. import validate as schemas


def _atomic_write_text(target: Path, text: str) -> None:
    """Replace target with text via a uniquely named same-directory staging file."""
    stage = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=target.parent,
            prefix=target.name + ".", suffix=".tmp", delete=False,
        ) as handle:
            stage = Path(handle.name)
            handle.write(text)
        stage.chmod(0o644)
        stage.replace(target)
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--region", default="morro-bay")
    args = parser.parse_args()
    previous = None
    if args.previous and args.previous.exists():
        previous = json.loads(args.previous.read_text())
        validate(previous)
    now = datetime.now(timezone.utc)
    snapshot = collect(now, previous, region_id=args.region)
    schemas.check("daily-feed", snapshot)  # raises ContractError before anything is written
    args.output.mkdir(parents=True, exist_ok=True)
    # Atomic files, then one atomic branch update in the publishing job.
    encoded = json.dumps(snapshot, separators=(",", ":"), allow_nan=False) + "\n"
    latest = args.output / "latest.json"
    _atomic_write_text(latest, encoded)
    archive = args.output / "history"
    archive.mkdir(exist_ok=True)
    (archive / (now.strftime("%Y-%m-%d") + ".json")).write_text(encoded)
    for old in archive.glob("*.json"):
        if old.stem < (now - timedelta(days=90)).strftime("%Y-%m-%d"):
            old.unlink()
    (args.output / "health.json").write_text(json.dumps({"generated_at": snapshot["generated_at"], **snapshot["health"]}, indent=2) + "\n")
    print(json.dumps(snapshot["health"], indent=2))


if __name__ == "__main__":
    main()
