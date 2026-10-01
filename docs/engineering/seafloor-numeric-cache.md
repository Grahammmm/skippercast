# Stable seafloor measurement encoding

JSON publishers may serialize an integral measurement as either `5` or `5.0`.
Previously, the source rows entered the reach input hash unchanged. Four saved
BSS receipts demonstrated Python-equal inputs with different serialized hashes;
ordinary runs repeated expensive terrain computation although measured results
were unchanged.

`load_manifest` now validates first, copies its input, and converts only
schema-declared continuous measurements to exact finite floats: native spacing,
reviewed geographic bounds, and mixed-resolution profile measurements. Integer
counts/years, booleans, unknowns, hashes, evidence, producer terms and files on
disk are preserved. A nonintegral value is not rounded; an integer that cannot
be represented exactly is rejected. The hash function, numerical implementation
pins, original/COG checksums, raster identity, source eligibility and current
spatial-screen rules are unchanged. There are no alternate hash aliases or
scientific-implementation exemptions.

## Acceptance evidence

The real tiny-survey reach test alternates integer and decimal encodings. All
three repeats return the identical checked receipt without footprint reads or
habitat extraction. Disabling normalization reproduces the measured-coverage
cache miss, proving the test exercises the original blocker. Existing tests
still reject changed rules, withdrawn sources and corrupted cached outputs.
Contract tests retain exact adjacent float values and reject nonfinite or
unrepresentable measurements. Catalog documents are not mutated.

Four real saved BSS input pairs converge to identical normalized hashes; the
committed proof contains hashes and no private geometry or raw metadata. Local
full GIS validation: 1,061 passed, 14 allowlisted skips, 3,808 subtests. Focused
manifest/reach checks: 23 passed, 3,037 subtests. Strict skip report, platform
regeneration, repository/web and diff checks passed.

## Existing caches and release

Legacy receipts can contain a mixture of integer and decimal spellings. Their
old text hashes may differ from the normalized representation, so this change
does **not** silently adopt or overwrite them. Do not trigger coastwide terrain
reprocessing simply to warm a new representation. Next: an explicit tested
metadata-only migration that verifies unchanged scientific inputs, numerical
implementation pins, source bytes and every output, preserves candidate geometry
and ranks, and retains a recoverable receipt. Changed science must still require
normal processing; MPA/security screening remains separate and mandatory before
public/export release.

This focused fix was rebased and revalidated on main `fdf42cd55`. Independent review and exact-head
CI remain required before merge. No new surveyed area, candidates, public ledger
or live locations are added by a cache fix. The full coastal rollout remains
unfinished.
