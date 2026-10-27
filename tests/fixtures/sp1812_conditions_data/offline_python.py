"""Process-local offline bootstrap for the unchanged repository scanner."""
from pathlib import Path
import runpy
import sys


def offline(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.bind"}:
        raise RuntimeError("SP1812_OFFLINE_BOUNDARY")


def main():
    root = Path(__file__).resolve().parents[3]
    target = root / "scripts/check_repository.py"
    if sys.argv[1:] != ["scripts/check_repository.py"]:
        raise SystemExit("only the unchanged repository scanner is admitted")
    sys.addaudithook(offline)
    sys.path.insert(0, str(root))
    sys.argv = [str(target)]
    print("SP1812_OFFLINE_INSTALLED", flush=True)
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
