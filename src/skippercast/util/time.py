"""Timestamps written into feeds, receipts and manifests."""
from datetime import datetime, timezone


def stamp(moment=None, *, to_utc=True):
    """ISO-8601 UTC time to the second with a `Z` suffix, e.g. `2026-09-28T12:07:40Z`.

    `moment` defaults to now. With `to_utc` (the default) an aware time is
    converted to UTC first (a naive one is taken as local time, as
    `datetime.astimezone` does). `to_utc=False` formats the fields as given and
    labels them `Z`: the forecast tile builder's historic format, identical for
    the UTC times it passes.
    """
    moment = moment or datetime.now(timezone.utc)
    if not to_utc:
        # Explicit year width: platform strftime('%Y') does not pad years < 1000.
        return (f'{moment.year:04d}-{moment.month:02d}-{moment.day:02d}'
                f'T{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}Z')
    return moment.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
