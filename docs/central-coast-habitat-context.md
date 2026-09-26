# Monterey–Point Conception habitat context

`scripts/build_central_habitat_context.py` adds a reproducible **research-only** reef layer to five preview regions between Santa Cruz and San Simeon. The existing Morro Bay survey targets and Point Arguello original-depth research outlines remain separate. The layer does not create any ranked fishing marks or GPX exports.

| Region | Source | Published patches | Qualification |
| --- | --- | ---: | --- |
| Pigeon Point–Monterey Bay | USGS original seafloor-character class 3 | 231 | Historical hard substrate only |
| Monterey–Point Sur | USGS original seafloor-character class 3 | 33 | Historical hard substrate only |
| Big Sur outer coast | PMEP rocky-reef HAPC compilation | 265 | Broad zone; no chart depth |
| South Big Sur–San Simeon | PMEP rocky-reef HAPC compilation | 43 | Broad zone; no chart depth |
| Cambria–San Simeon | USGS original seafloor-character class 3 | 3 | Historical hard substrate only |

Counts reflect a September 2026 build and can change when the public source changes. USGS source and metadata URLs travel with each feature. The PMEP features link to the [public map service](https://gis.psmfc.org/server/rest/services/PMEP/West_Coast_Nearshore_CMECS_Substrate_Habitat/MapServer/1); its rocky-reef HAPC classification is habitat context, not a fish observation or a legal fishing designation. Core and seaward PMEP zones are included; the latter reaches 100 m (328 ft), so the 300-ft fishing-depth limit **cannot** be inferred from these shapes. Smaller PMEP fragments below 5,000 m² are omitted from the display to avoid a cluttered map; absence from this layer does not mean absence of reef.

The builder clips every outline to its region, removes the official CDFW MPA footprints with a 102 m processing margin, and stores source and MPA hashes in the output. The browser also screens full geometry against current closure data and withholds the layer if that check fails. The layer remains outside the fishing target, ranking and export pipelines. `tests/test_central_habitat_context.py` checks region bounds, legal separation and non-target flags.

To rebuild, install `requirements-survey.txt` into an isolated environment and run:

```bash
PYTHONPATH=src python scripts/build_central_habitat_context.py
PYTHONPATH=src python -m skippercast.platform.build
python -m unittest tests.test_central_habitat_context
```

To graduate any patch to a 1–3 fishing target, the regional pipeline still needs source-native bathymetry in a chart-compatible vertical datum, per-cell depth uncertainty, a reviewed 0–300 ft screen, independent substrate/relief evidence, charted hazard and approach review, current MPA/groundfish exclusion review, and a reproducible source and rights receipt. The current context does **not** satisfy that gate. Big Sur has the largest depth and chart gap, and neither the number of polygons nor the displayed area measures fishing quality.
