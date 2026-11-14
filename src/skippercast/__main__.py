"""Small, explicit entry points; no command schedules jobs or sends messages."""

import argparse
import sys

from skippercast import __version__


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("command", choices=["atlas", "validate"])
    # Let the selected command own its flags, including --help. Otherwise the
    # root parser consumes subcommand help before it reaches the real parser.
    args = parser.parse_args(argv[:1])
    remaining = argv[1:]
    if args.command == "validate":
        from skippercast.validate import main as validate
        return validate(remaining)
    from skippercast.atlas.export import main as export
    return export(remaining)


if __name__ == "__main__":
    raise SystemExit(main())
