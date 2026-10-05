"""Fleet run directories and state (design section 4).

State lives under ``$SKIPPERCAST_FLEET_VAR`` (default ``<repo>/var/fleet``,
gitignored); on Hermes it is set outside any checkout. One run is
``<FLEET_VAR>/<region>/runs/<run_id>/`` holding the step outputs
(``candidates.jsonl``, ``resolved.jsonl``, ``facts.jsonl``), ``state.json``
(per-step status) and ``report.json``.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any, Iterable, Mapping

from ..paths import repo_root

RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$")


def fleet_var(environ: Mapping[str, str] | None = None) -> Path:
    configured = (os.environ if environ is None else environ).get("SKIPPERCAST_FLEET_VAR", "").strip()
    return Path(configured).expanduser() if configured else repo_root() / "var" / "fleet"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


def _write_json(path: Path, doc: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


class Run:
    """One run of one region; reopening the same run id resumes it."""

    def __init__(self, region: str, run_id: str | None = None, var: Path | None = None):
        self.region = region
        self.id = run_id or new_run_id()
        if not RUN_ID.match(self.id):
            raise ValueError(f"run id {self.id!r} does not match YYYYMMDDTHHMMSSZ-xxxxxx")
        self.var = Path(var) if var is not None else fleet_var()
        self.dir = self.var / region / "runs" / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.var / region / "inputs").mkdir(exist_ok=True)
        self.state_path = self.dir / "state.json"
        self.state = (json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.exists()
                      else {"run_id": self.id, "region": region, "created_at": now(), "steps": {}})

    @property
    def http_cache(self) -> Path:
        return self.var / self.region / "http-cache"

    def staging_db(self) -> Path:
        path = self.var / "staging" / f"{self.region}.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def step_started(self, step: str, sink: str) -> None:
        self.state["steps"][step] = {"status": "running", "sink": sink, "started_at": now()}
        _write_json(self.state_path, self.state)

    def step_finished(self, step: str, counts: Mapping[str, Any], error: str | None = None) -> None:
        self.state["steps"][step].update(status="failed" if error else "done", finished_at=now(),
                                         counts=dict(counts), error=error)
        _write_json(self.state_path, self.state)

    def write_jsonl(self, name: str, rows: Iterable[Mapping[str, Any]]) -> int:
        count = 0
        with (self.dir / name).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
                count += 1
        return count

    def read_jsonl(self, name: str) -> list[dict]:
        path = self.dir / name
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def write_report(self, report: Mapping[str, Any]) -> None:
        _write_json(self.dir / "report.json", {"run_id": self.id, "region": self.region, **report})
