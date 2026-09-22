# Species search plans

A selected species now has a map shortlist, rather than only a distribution guide. The shortlist is a place to investigate with sonar and bait observations, not a prediction of catching a fish. Each regional target has its own habitat, technique, missing observations, and source links in `catalog/search-methods.json`.

## Data flow

1. Review the region’s ecological dossier and source footprints. Distinguish species, life stage, method and geography. Practical presentation suggestions are labeled synthesis, not measured optimal catch conditions.
2. Run `python scripts/build_search_plans.py` in the pinned survey environment (`requirements-survey.txt`). This compiles existing habitat and qualified reef outlines, records input hashes, clips to regional fishing bounds, and subtracts all imported protected/closure geometry with a conservative margin. Invalid geometries are withheld in the artifact’s `rejected` list. No circles, hulls, expanded habitat or invented bay habitat are created.
3. Run `PYTHONPATH=src python -m skippercast.platform.build` to update manifests. New regions use the same compiler and must have their own ecological profile and matching source footprints.
4. In the browser, the selected time and target trigger a four-hour fishing-window comparison at suitable nearby regional marine samples. All five hourly endpoints must score. Samples more than 12 nautical miles away are withheld; this is a disclosed coverage limit, not demonstrated fine-scale accuracy. Transit, island shelter, entrance conditions and catch probability remain separate.
5. Existing 30-minute habitat/forecast updates supply dated ocean tiles. Pelagic targets can inspect three adjacent populated native WCOFS cells as a single search strip. No masked cells are bridged. Water transitions order otherwise comparable strips; this is an uncalibrated search heuristic. A thermal reference never proves presence or absence. Beyond actual ocean model coverage the dynamic search strips disappear, even when weather has a longer horizon.
6. The shortlist displays up to three source footprints in the visible map. Current full-polygon MPA screening runs again before drawing. Boat-condition scores do not certify fish presence or legal access; Rules remains the authority-status surface. These exploratory areas are intentionally not depth-qualified chartplotter exports.

Survey changes require rerunning the compiler and reviewing its rejected records. Weather and ocean changes require no copied region-specific code. Run `node --test tests/test_search_plans.mjs` and the native `tests/test_search_plan_geometry.py` fixtures before publishing.

## Research review, September 22, 2026

- NOAA’s [yellowtail biology account](https://www.fisheries.noaa.gov/west-coast/science-data/yellowtail-research-southwest) supports mobile forage searching. Its aquaculture experiments are not wild-fish optimum temperatures. The [2001 CDFW yellowtail account](https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=34379) provides historical ecological context, never today’s locations or regulations.
- CDFW’s [fish life-history table](https://wildlife.ca.gov/Conservation/Marine/Life-History-Fish) distinguishes reef/kelp, sediment and bay habitats. In particular, ocean whitefish use the water column over hard and soft bottom. Broad depth ranges are not local soundings.
- [NPS lobster habitat](https://www.nps.gov/chis/learn/nature/california-spiny-lobster.htm) supports rocky/vegetated habitat, not individual dens. Night operations require their actual forecast window.
- NOAA [bluefin](https://www.fisheries.noaa.gov/species/pacific-bluefin-tuna) and [albacore](https://www.fisheries.noaa.gov/species/pacific-albacore-tuna) accounts support separate mobile-fish strategies, not a universal tuna SST optimum.
- CDFW [bonito](https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=34441) and [barracuda](https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=34231) historical reports supply ecology and methods; old catch totals and seasonal associations are not current schools.
- Several Marine Species Portal direct reads timed out. The OPC barracuda PDF request was rejected. Those attempts add no newly verified evidence. The Sea Grant bonito page has inconsistent metric/imperial depths and mixed-species references; its numeric depth claims are not used.
- CDFW document 151024 is an MPA environmental comments volume, not a dedicated whitefish habitat source. The new whitefish method links the actual life-history table instead.

Current bait density, fish identification, thermocline, bottom current, live kelp/paddy positions and spatially verified recent catches remain missing. The map makes those limitations explicit rather than converting them into a confident bite score.
