# Ventresca original producer contract

The nine native grids in PR159 remain private because the existing producer
rights validator hardcodes the earlier `harold_heath` archive. A matching
hash-bound producer review fails only on the newly inspected archive prefix.
Add the explicitly reviewed `ventresca` archive to that same producer profile.
This does not grant permission to arbitrary NOAA-distributed data.

The real probe also found five Big Creek drafts with publisher still unknown.
Populate their producer from the original archive metadata before qualification;
the validator correctly rejects missing producer identification. Do not relax
that condition. This private-draft correction does not change the catalog.

The [official CSUMB policy](https://csumb.edu/undersea/sfml-data-library/),
rechecked September 30, 2026, permits public use, requests producer credit,
requires express permission for for-profit use and disallows navigation use.
The [original SlateRock report](https://www.ngdc.noaa.gov/ships/ventresca/SlateRock_mb.html)
identifies CSUMB SFML as the source organization and 2006 acquisition dates.
The [SCC01 original report](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block01_mb.html)
and original embedded metadata identify the same producer. The text browser
could not reopen SCC01 during this review; its previous direct HTTP receipt and
downloaded original metadata remain the inspection evidence. Do not treat that
browser failure as a newly checked successful response.

Tests reproduce qualification through the normal manifest helper for a checked
Ventresca source, while rejecting changed hashes, wrong producer, commercial
or navigation permission, other cruise paths, lookalike hosts and non-HTTPS
URLs. All existing producer review fields and per-source receipts are required.
No source row is automatically promoted, no physics recomputed, and no current
spatial restriction bypassed. After review, qualify source rows explicitly,
adopt unchanged private processing, then screen complete polygons before release.

The real cached-source probe succeeds for all nine native originals after the
explicit draft producer review. Every original and normalized hash still matches;
no file was downloaded, no terrain rerun and no catalog row changed. The receipt
is private `var/seafloor/next-original-native/ventresca-rights-probe.json`.
