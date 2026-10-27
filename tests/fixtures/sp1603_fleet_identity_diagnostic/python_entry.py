"""File-only entrypoints: actual producer, guard probe, or staged unittest -m bootstrap.

This process is fixture-owned. Guards are installed before any product import;
no source extraction or encoder oracle is used. No peer interpreter is modified.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import socket
import sqlite3
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]


def install_offline(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ["SKIPPERCAST_ROOT"] = str(ROOT)
    os.environ["SKIPPERCAST_FLEET_VAR"] = str(output / "synthetic-fleet")
    os.environ["SKIPPERCAST_VAR"] = str(output / "synthetic-var")
    os.environ.pop("SKIPPERCAST_NETWORK", None)
    tempfile.tempdir = str(output)

    def denied(*args, **kwargs):
        raise RuntimeError("SP1603_OFFLINE_NETWORK_MODEL_SENTINEL")

    # Patch before imports capture urlopen as a bound default (WorkerSink etc.).
    socket.create_connection = denied
    socket.getaddrinfo = denied
    urllib.request.urlopen = denied
    urllib.request.OpenerDirector.open = denied
    original_connect = sqlite3.connect

    def connect(database, *args, **kwargs):
        if database != ":memory:":
            path = Path(database).resolve()
            if not path.is_relative_to(output):
                raise RuntimeError("SP1603_LIVE_STORE_SENTINEL")
        return original_connect(database, *args, **kwargs)

    sqlite3.connect = connect

    def audit(event, args):
        if event in {"socket.connect", "socket.bind", "socket.getaddrinfo", "subprocess.Popen", "os.system"}:
            raise RuntimeError("SP1603_OFFLINE_NETWORK_MODEL_SENTINEL")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
            if writing and not path.is_relative_to(output):
                raise RuntimeError("SP1603_WRITE_SENTINEL")
            if path.is_relative_to(ROOT / "var"):
                raise RuntimeError("SP1603_LIVE_STORE_SENTINEL")
    sys.addaudithook(audit)
    return denied


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["producer", "unittest", "guard-probe"])
    parser.add_argument("--fixture", type=Path, default=FIXTURE / "corpus.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    denied = install_offline(args.output)
    if args.mode == "guard-probe":
        for action in (lambda: urllib.request.urlopen("https://offline.invalid"),
                       lambda: socket.create_connection(("offline.invalid", 443)),
                       lambda: sqlite3.connect(ROOT / "var" / "not-a-real-store.sqlite")):
            try:
                action()
            except RuntimeError as error:
                if "SP1603_" not in str(error):
                    raise
            else:
                raise RuntimeError("guard did not reject")
        # Import real sink only after defaults are captured under the sentinels.
        from skippercast.fleet.sinks import WorkerSink
        if (WorkerSink.__init__.__kwdefaults__ or {}).get("opener") is not denied:
            raise RuntimeError("bound opener was not guarded")
        print(json.dumps({"checks": 4, "passed": 4, "skipped": 0}))
        return 0
    if args.mode == "unittest":
        # File-based equivalent of python3 -m unittest, with clone-first sys.path
        # and pre-import guards; the unchanged exact class is the sole selector.
        sys.argv = ["python3 -m unittest", "-v", "tests.unit.test_fleet_sinks.SqliteSinkTests"]
        runpy.run_module("unittest", run_name="__main__", alter_sys=True)
        return 0
    from skippercast.fleet import ops
    if Path(ops.__file__).resolve() != ROOT / "src/skippercast/fleet/ops.py":
        raise RuntimeError("wrong producer checkout")
    corpus = json.loads(args.fixture.read_text(encoding="utf-8"))
    rows = []
    for case in corpus["cases"]:
        text = ops.canonical_json(case["value"])
        data = text.encode("utf-8")
        rows.append({"id": case["id"], "text": text, "utf8_hex": data.hex(),
                     "value_key": ops.value_key(case["value"])})
    print(json.dumps({"runtime": {"version": sys.version, "executable": sys.executable},
                      "source": "src/skippercast/fleet/ops.py",
                      "source_sha256": hashlib.sha256(Path(ops.__file__).read_bytes()).hexdigest(),
                      "rows": rows}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
