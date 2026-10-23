"""Audit repro (2026-10-22): the public-domain branch of source_rights trusts the label alone.

`skippercast.seafloor.rights.source_rights` returns cleared, for-profit-usable
terms for any row whose `license` is `public-domain-us-gov`, even when its URL
is one of the CSUMB SFML archives on NOAA NCEI and its publisher is CSUMB. The
module's own rule is "distributor hosting grants no new rights", and
`source_scope.government_row` admits rows by the same label, so one catalog
typo would move noncommercial CSUMB data into the for-profit/government path.
"""
import pytest

from skippercast.seafloor.rights import CSUMB_ARCHIVES, source_rights


def test_csumb_archive_cannot_clear_for_profit_by_label():
    row = {'id': 'synthetic-csumb', 'license': 'public-domain-us-gov',
           'publisher': 'CSUMB (NOAA NCEI distributor)',
           'url': CSUMB_ARCHIVES[0] + 'BSS_Block99/products.tar.gz', 'sha256': 'a' * 64}
    with pytest.raises(ValueError):
        source_rights(row, use='for-profit')


import os as _audit_os  # noqa: E402

import pytest as _audit_pytest  # noqa: E402

pytestmark = _audit_pytest.mark.skipif(
    _audit_os.environ.get("SKIPPERCAST_AUDIT_CLOUD") != "1",
    reason="audit repro (fails on purpose): set SKIPPERCAST_AUDIT_CLOUD=1",
)
