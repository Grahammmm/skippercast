# Quickstart

Choose the atlas if you want fishing research on your chartplotter. Choose the Python tools if you want to collect and inspect forecast evidence or develop the project.

## Use the atlas without installing anything

1. Read the [atlas coverage and limits](../atlas/avila-point-estero-2026-09-20/README.md).
2. Download its `exports/complete.gpx` as a file. A GitHub preview page is not the GPX file; use the download/raw-file control.
3. Back up your chartplotter data, then follow the [iNavX instructions](inavx.md).
4. For a searchable list, download `exports/spot-notes.html` and open it locally in a browser. The page makes no external requests.

## Run the offline demonstration

Use Python 3.11+ with IANA time-zone data available. macOS and typical Linux installations provide it; Windows users may need the standard `tzdata` package for Python's `zoneinfo` support.

macOS / Linux, from the repository root:

```bash
PYTHONPATH=src python3 -m skippercast demo
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m skippercast demo
python -m unittest discover -s tests -v
```

No Python package dependencies are needed for the core tools; the optional Windows `tzdata` package supplies system time-zone data. Tests use saved/synthetic fixtures and temporary directories. They do not contact providers, schedule tasks, or deliver messages.

## Optional editable installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
skippercast demo
```

On Windows, activate with `.venv\Scripts\Activate.ps1`. Installing build tools may use the network. Repository data and example profiles stay in this checkout; they are not bundled inside a Python wheel.

## Collect live evidence

From the repository root:

```bash
PYTHONPATH=src python3 -m skippercast collect \
  --config configs/morro-bay.example.json \
  --output var/runs/first-check
```

Use a new output directory for every run. The collector will not overwrite a prior run. This command contacts the sources described in the [source register](data-sources.md). A system `curl` is used for CDFW pages when available; TLS verification remains enabled. Sources can fail or return incomplete fields. A nonzero exit status means the collection or screen is incomplete: inspect its saved manifest and gaps rather than treating it as “no good dates.”

Read the saved raw sources, metadata, and `screen.json` together. Retrieval time is not forecast issue time. Passing numerical limits does not produce a recommendation. The [forecast workflow](forecast-workflow.md) explains the additional review and [assessment rubric](assessment-rubric.md) defines the scores.

The supplied profile is a **regional Morro Bay example**, not a geographic discovery engine. Changing coordinates alone does not change the NWS zone, harbor, tide station, buoy selection, regulatory sources, or navigation requirements. Those must be reviewed before adapting it to another location.

## Re-export the atlas

```bash
PYTHONPATH=src python3 -m skippercast atlas validate \
  --data atlas/avila-point-estero-2026-09-20/data/atlas.json

PYTHONPATH=src python3 -m skippercast atlas export \
  --data atlas/avila-point-estero-2026-09-20/data/atlas.json \
  --output var/atlas-preview
```

This rebuilds GPX, GeoJSON, and HTML from the included reviewed data. It does **not** rerun original multibeam analysis, update restrictions, or establish current depths. See [atlas methodology](atlas-methodology.md) for what is and is not reproducible in this release.

## Keep local information local

Use ignored `var/` for working outputs and a `*.local.json` file for your own settings. Do not commit account tokens, messaging destinations, personal trip logs, raw source archives, or delivery receipts. No Telegram transport, account connection, schedule, or production alert state is included.
