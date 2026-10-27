# SP1805 shoreline source-date validation

`coastlineMark` now makes a clicked shoreline feature selectable only when its existing `source_date` text is both in the supported `YYYY-MM-DD` form and a real Gregorian calendar date. It rejects impossible month/day combinations and applies the Gregorian century leap-year rule without parsing through local time, rewriting accepted text, or imposing an age/future cutoff. The card's metadata and attribution construction are unchanged.

Offline coverage and acceptance are provided by `tests/test_sp1805_shoreline_date.mjs`, its synthetic properties fixture, and `scripts/accept_sp1805_shoreline_date.py`. This scoped acceptance does not establish full-repository, semantic, legal, scientific, publication, or release acceptance.
