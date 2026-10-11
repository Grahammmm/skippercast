"""``python -m skippercast.fleet.ais <command>``: ``listen`` runs the AIS listener (design.md section 10),
``process`` the processor job, ``backfill`` the MarineCadastre backfill, ``validate`` the classifier's
validation against hand labels (section 11), ``watch-check`` the watched gate over the stored watch rows and
``schedule-precision`` the precision of schedule-correlation on a history window.
"""
from __future__ import annotations

import sys

COMMANDS = ("listen", "process", "backfill", "validate", "watch-check", "schedule-precision")


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
    if command == "backfill":
        from .backfill import main as backfill
        return backfill(rest)
    if command == "validate":
        from .validate import main as validate
        return validate(rest)
    if command == "watch-check":
        from .gate import main as watch_check
        return watch_check(rest)
    if command == "schedule-precision":
        from .schedule import main as schedule_precision
        return schedule_precision(rest)
    return 2   # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
