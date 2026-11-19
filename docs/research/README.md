# Research notes

Hermes should start with the [feature specs](specs/README.md). That roadmap is the recommended build order for the 2026-11-19 research package. [morro-bay-tuna.md](morro-bay-tuna.md) is a separate method note for the Morro Bay tuna search overlay.

The [`research/`](../../research/README.md) directory at the repository root is audit and screening tooling. Feature work for Hermes is this folder.

## Folders

| Folder | What it holds |
| --- | --- |
| [specs/](specs/README.md) | Ten feature specs in the rea format (`spec.md`, `plan.md`, `tasks.md` per feature), plus a generated `NN-slug.md` for each. Edit the directory files. `specs.json` is the machine-readable index. |
| [inspiration/](inspiration/skippercast_inspiration.md) | Map-visual inspiration from public X posts: the write-up, the JSON, sampled palettes (`palettes.json`), cmocean stops (`cmocean_stops.json`) and the downloaded images. |
| [competitors/](competitors/competitors.md) | Competitive notes on 36 marine apps, the JSON, and App Store and website screenshots. |
| [data-sources/](data-sources/README.md) | Ingest guides for sources those apps use: endpoints, auth, licence notes and download steps. |

## Build order

The full table, dependency graph and ground rules are in [specs/README.md](specs/README.md). The lanes are:

- **Lane A (map):** 01 point readout and colour ranges, then 02 observed look-back, then 05 chlorophyll edges, eddies and sea-surface height, then 07 subsurface depth ladder after the owner confirms that scope.
- **Lane B (account and server):** 03 spot water alerts, then 06 catch conditions. Spec 06 also needs spec 02.
- **Lane C (boat):** 04 heading-aware comfort and 08 GPX import and fuel. Each can start on its own.
- **Owner-gated:** 09 Text Advisor launch and 10 coverage and distribution, when the owner acts. Prepare the work, then stop at the gate.

## Package limits

Sample files named in the data-source guides (the 2026-11-19 NetCDF, GRIB and CSV pulls) are not in the repository. The guides keep the endpoints and the download steps.

Competitor `image` fields that point at `images/composites/` refer to canvas strips from the research page. Those strips are not in this repository. The raw screenshots are in [competitors/images/](competitors/images).

The rea tool checkout used while writing the specs is not in the repository. Its evidence bundles are in [specs/rea-evidence/](specs/rea-evidence).

The images are reference screenshots: 155 files, about 33 MB. This repository has no Git LFS. Each binary file is pinned by SHA-256 in `scripts/web-vendor-sha256.json`, which `scripts/check_repository.py` requires. They are third-party pictures from X posts and app listings. Confirm reuse before a product surface displays one.
