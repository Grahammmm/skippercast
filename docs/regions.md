# Add a coastline

A regional package is configuration and evidence, not a fork of the app. The [Southern California rollout](southern-california.md) validates multiple local observation/advisory contexts and a separate jurisdiction in one regional package. Morro Bay–Avila is the working reference; Cambria–San Simeon validates the same map, forecast, jurisdiction and pipeline with a different footprint and geological source.

1. Define a stable region ID and explicit WGS84 extent, timezone, departure harbor, boat/depth preferences, target species and jurisdiction. Offshore tuna samples may extend beyond the bottom-fishing extent. Do not inherit a neighboring port's travel assumptions silently.
2. Run the needs report. Use the discovery skill to identify primary regional providers. Record original dataset footprint, variables, native precision, time coverage, rights and actual access. A station outside the region can be an explicitly labeled reference, not a local measurement.
3. Bind sources in `regions/<id>/region.json`, record regional coverage and the reason for each gap. Use a jurisdiction package for shared rules. Map public assets separately from raw local inputs. Use null for absent datasets; never reuse another region's catch or AIS layer to fill the map.
4. Import approved data through a provider adapter. Qualify fishing geometries with the original depth grid, datum, native masks, depth limit and full closure geometry. Keep context polygons separate from qualified targets. Existing legal exclusions remain conservative across every MPA, even where limited species exceptions exist.
5. Compile and inspect the package. Preview status allows explicit geological context and regional forecasts while unavailable targets stay empty. Published fishing targets require ready depth, substrate and MPA coverage. A production-ready forecast also needs fresh observations, advisories and confidence checks at runtime.
6. Add the region to the existing daily and half-hourly workflow discovery (non-draft packages are discovered automatically). Confirm its first feed receipt before claiming the updater works. No new per-region scheduler or copied app is needed.

```bash
PYTHONPATH=src python -m skippercast.platform validate --region cambria-san-simeon
PYTHONPATH=src python -m skippercast.platform.build
PYTHONPATH=src python -m skippercast.pipeline --region cambria-san-simeon --output var/north-daily
PYTHONPATH=src python -m skippercast.pipeline.live --region cambria-san-simeon --output var/north-live.json
python scripts/check_web.py
python scripts/check_repository.py
```

The browser loads `regions/index.json`, selects a package with `?region=<id>`, then loads shared components. Region changes reload the page so selection, forecast requests and caches cannot remain attached to the previous region. The default region module is generated from configuration for offline tests and tools. Region identity is checked before consuming feeds or survey windows. Only the legacy Morro Bay feed may omit a region ID.

The Cambria–San Simeon preview imports [USGS SIM 3327 geology](https://pubs.usgs.gov/sim/3327/), downloaded and checked on September 21, 2026. Its 2015 interpretation is broad context. It does not supply a native grid adequate for this app's 200-foot target qualification or individual-rock imagery. The superficially relevant NOAA H13089 title includes San Simeon, but its published footprint is offshore/south of the intended nearshore expansion; a title alone is not coverage. CSUMB-derived native grids remain withheld where redistribution is unresolved. These gaps are deliberate and visible.

```bash
# Optional GIS environment: numpy, rasterio, shapely, pyproj, pyshp.
python scripts/import_usgs_geology.py --region cambria-san-simeon --zip /local/Geology_SanSimeon.zip
python scripts/build_bottom_views.py --region morro-bay --manifest /local/survey-manifest.json
```

Use `$skippercast-discover-data`, `$skippercast-ingest-data`, and `$skippercast-add-region` for future work. Their maintained sources live under `skills/`; `python scripts/install_research_skills.py` installs them into the current user's Codex skills folder. Run the system skill validator on the installed copies when available.

Roll back a region by republishing the previous coherent app/package version; mark a problematic new package draft to remove it from discovery. Retain prior feed source times. Do not relabel retained data as a new observation. Existing regions can keep working while one preview is withheld.
