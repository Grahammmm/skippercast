# Species fishing strategies

Every published target has a reviewed **starter method** in `catalog/primary-strategies.json`. The regional compiler `scripts/build_primary_strategies.py` selects only targets offered by each `regions/<id>/region.json` and writes `dist/regions/<id>/strategies.json`. It fails if a new target lacks a complete method. The selected species field guide shows the plan, habitat signs, rig, on-water sequence and adjustments. The map's search-area card uses the same regional packet.

These are practical starting presentations for boat anglers, not calibrated catch recipes. Habitat evidence comes from each region's ecological profile and source-linked search methods. CDFW's [groundfish summary](https://wildlife.ca.gov/Fishing/Ocean/Regulations/Groundfish-Summary), [descending-device guidance](https://wildlife.ca.gov/Conservation/Marine/Groundfish/Rockfish-Barotrauma-and-Descending-Devices), [ocean salmon rules](https://wildlife.ca.gov/Fishing/Ocean/Regulations/Salmon), [lobster methods](https://wildlife.ca.gov/conservation/marine/invertebrates/lobster), and [crab rules](https://wildlife.ca.gov/conservation/marine/invertebrates/crabs) anchor gear that has specific legal requirements. Where no agency recommends a precise rig, the packet labels a general starter option rather than asserting an optimum line class, sinker size, lure color, tide, temperature or depth.

The Rules card remains the authority for the selected date, position and method. Strategy text does not open a closed season, authorize fishing inside an MPA, or prove that fish are at a search area. A species plan should be revised when a new habitat study, local method restriction or prospective trip log provides better evidence. Changes require a dated catalog review and regeneration of all affected regional packets:

```bash
python scripts/build_primary_strategies.py
python -m unittest tests.test_primary_strategies -v
node --test tests/test_primary_strategy.mjs
```

For a new coast, research local species and legal methods first, add its targets to the region manifest, supply missing strategies, then rebuild. The compiler rejects incomplete coverage instead of silently copying a tactic to a new species. Region-specific habitat and conditions remain in the existing ecology, forecast, survey and rules pipelines.
