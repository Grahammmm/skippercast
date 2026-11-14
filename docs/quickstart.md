# Quickstart

Choose the atlas if you want fishing research on your chartplotter. Choose the Python tools if you want to validate files, re-export the atlas, or develop the project.

## Use the atlas without installing anything

1. Read the [atlas coverage and limits](../atlas/avila-point-estero-2026-09-20/README.md).
2. Download its `exports/complete.gpx` as a file. A GitHub preview page is not the GPX file; use the download/raw-file control.
3. Back up your chartplotter data, then follow the [iNavX instructions](inavx.md).
4. For a searchable list, download `exports/spot-notes.html` and open it locally in a browser. The page makes no external requests.

## Install and inspect the Python tools

Use Python 3.11+ from the repository root.

macOS / Linux:

```bash
python3 -m pip install -e ".[test]"
python3 -m skippercast --help
python3 -m pytest -m "not gis"
```

PowerShell:

```powershell
python -m pip install -e ".[test]"
python -m skippercast --help
python -m pytest -m "not gis"
```

No Python package dependencies are needed for the core tools (the tests need the pinned `test` extra: pytest, jsonschema, moto). Tests use saved/synthetic fixtures and temporary directories. They do not contact providers, schedule tasks, or deliver messages.

## Optional editable installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
skippercast --help
```

On Windows, activate with `.venv\Scripts\Activate.ps1`. Installing build tools may use the network. Repository data and example profiles stay in this checkout; they are not bundled inside a Python wheel.

Optional extras install the pinned scientific and publishing tools: `ocean` (NetCDF/GRIB decoders), `sst`, `survey` (original-survey and seafloor geometry; Python 3.12+), `publish` (R2), `test` (JSON Schema), `seafloor` (survey + publish + test) and `dev` (all of them), for example `python -m pip install -e ".[survey,test]"`. They mirror the `requirements-*.txt` files, which the scheduled jobs still use; a test fails if the two drift.

Code finds `regions/`, `catalog/` and `dist/` through `skippercast.paths.repo_root()`: the source checkout by default, or the directory named by `SKIPPERCAST_ROOT`.

## Validate a file

```bash
python3 -m skippercast validate sources-catalog catalog/sources.json
```

Schema validation needs the optional `jsonschema` dependency included in the `test` extra. It checks file structure, not current source freshness or whether a trip qualifies.

## Re-export the atlas

```bash
python3 -m skippercast atlas validate \
  --data atlas/avila-point-estero-2026-09-20/data/atlas.json

python3 -m skippercast atlas export \
  --data atlas/avila-point-estero-2026-09-20/data/atlas.json \
  --output var/atlas-preview
```

This rebuilds GPX, GeoJSON, and HTML from the included reviewed data. It does **not** rerun original multibeam analysis, update restrictions, or establish current depths. See [atlas methodology](atlas-methodology.md) for what is and is not reproducible in this release.

## Keep local information local

Use ignored `var/` for working outputs and a `*.local.json` file for your own settings. Do not commit account tokens, messaging destinations, personal trip logs, raw source archives, or delivery receipts. No Telegram transport, account connection, schedule, or production alert state is included.
