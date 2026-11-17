# Second seafloor scope: private, physical-only planning and runs

This describes tooling only. No second scope, reach, ledger row or screen approval is committed: a real second scope is G decision D2, and a valid config file is neither human review nor that approval.

## Commands

All three commands take the existing `--scope-config PATH` (inside the repository). Nothing is chosen implicitly or by environment, and leaving the option out keeps the central behaviour unchanged.

```text
python -m skippercast.seafloor reaches --scope-config catalog/<scope>.json
python -m skippercast.seafloor plan --scope-config catalog/<scope>.json [--physical-only] [--max-new N]
python -m skippercast.seafloor run --scope-config catalog/<scope>.json --reach ID --physical-only
```

- `reaches` builds the isolated reference under `var/seafloor/scopes/<id>/` (ledger, reaches, cells, build receipt).
- `plan` reads that reference. Without `--physical-only` every unprocessed reach is `held` and no batch is chosen. With it, the usual ranking and `--max-new` apply, `screen_reviewed` is always false, and only complete private receipts for this exact scope, config, reference and sources count as progress. Window overlap stays a scheduling estimate, never a measurement.
- `run` refuses without `--physical-only` and refuses `--fetch`. Output goes only to `var/seafloor/scopes/<id>/private-reaches/<reach>/`.

## What stays held

A noncentral run always uses the held `scope-screen-contract-unavailable` screen, so every habitat candidate is held, tier 2 and tier 3 stay zero and the receipt says `publication_prohibited`, even for public-domain sources. It never updates any ledger (including the isolated reference one) and never publishes; `publish` for a noncentral scope stays refused. Source admission (government and rights policy, reviewed bounds, original and normalized verification, substrate and terrain support) is unchanged. Private measured progress is not authoritative ledger state.

## Verification before any read or write

Before ingest, caching or writing, the scope's ledger, reach catalog, cells and build receipt must agree: same scope ID, unique non-empty reach IDs, identical reach sets in ledger and catalog, valid cell owners, one `input_hash`, the config SHA-256 recorded in the receipt, and every output hash in the receipt. Anything missing, stale, corrupt or from another scope is refused with no fallback to central artifacts. Private output paths are confined to the scope directory (a symlink escape is refused). Run and checkpoint keys include the full scope identity and the digest of `scoped_processing.py`. This is not a race-free sandbox.

## Cache effect

`run.py` changed, so its digest, which is part of the central physical-cache key, changed too. Retained central private caches therefore miss once. Old receipts are not adopted or migrated, and nothing here regenerates the central ledger or reference; recomputing them is later reviewed private work (see MGL-11), not permission granted by this change.

## Limits

D2 (real scope/reach/ledger commitment), D4, D5 and D6 stay with G. Upload, R2, workflow dispatch and screen refresh are out of scope.
