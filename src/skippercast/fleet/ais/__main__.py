"""``python -m skippercast.fleet.ais <command>``: ``listen`` runs the AIS listener (design.md section 10),
``process`` the processor job (section 11).

The backfill (CF-47) joins here as a further command.
"""
from __future__ import annotations

import sys

COMMANDS = ("listen", "process")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in COMMANDS:
        print(f"usage: python -m skippercast.fleet.ais {{{','.join(COMMANDS)}}} ...", file=sys.stderr)
        return 2
    command, rest = argv[0], argv[1:]
    if command == "listen":
        from .listener import main as listen
        return listen(rest)
    if command == "process":
        from .process import main as process
        return process(rest)
    return 2   # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
