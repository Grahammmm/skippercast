# Native Slate Rock, SCC and Big Creek batch

This source-only batch adds nine privately qualified original grids: six Big
Creek/Lopez Point 2 m and 5 m grids inspected in the preceding adapter proof,
and three new 2 m SCC Block01, SCC Block19 and SlateRock grids. It depends on
the bounded nested-original adapter in PR #158. Every previous catalog row is
unchanged. No public ledger, map bundle or export is changed.

Native inspection evidence is in
`catalog/csumb-slate-scc-native-sources.json` and the preceding Big Creek proof.
The three new original archives total 930,739,062 bytes. SCC01 has 2010 survey
dates; SCC19 mixes 2010 and 2011, so its catalog year remains unknown; SlateRock
has 2006 dates. Preserve NAVD88 and the documented Geoid09 detail where present.
Grid spacing is not positional accuracy. Per-cell uncertainty and interpolation
masks remain unknown. NOAA distributes CSUMB originals; these are not federal
public-domain data or independent corroboration of the same acquisition.

Four ordinary private runs completed at native spacing: new Arguello/Conception
r02, southern Big Sur/San Simeon r03 and Big Sur r02, plus maintenance/expansion
of existing Big Sur r03. Baselines include prior public and private caches.
Selected valid footprint increased from 6.817239611 to 76.356429976 km²:
**69.539190365 km² net**. Physical candidates increased from 88 to 912:
**824 net**. Of the 912 resulting candidates, 856 have supported species ranks
and 56 retain unknown ranks. These are habitat suitability results, not catches.
See `slate-scc-private-proof-2026-09-30.json` for reach totals and run hashes.

Reproduce with the shared runner, retaining the checked original caches:

```sh
export PYTHONPATH=src:.
python -m skippercast.seafloor plan --physical-only --max-new 3 --json
python -m skippercast.seafloor run --reach point-arguello-conception-r02 --physical-only
python -m skippercast.seafloor run --reach south-big-sur-san-simeon-r03 --physical-only
python -m skippercast.seafloor run --reach big-sur-coast-r02 --physical-only
python -m skippercast.seafloor run --reach big-sur-coast-r03 --physical-only
```

Release remains held: the producer-rights checker currently only accepts the
previously reviewed `harold_heath` archive prefix. It rejects `ventresca` even
when the producer review fields match. Qualify that original archive explicitly
with positive and negative tests rather than bypassing rights or mislabeling it
public domain. Then promote rights in place, adopt unchanged private physics,
and apply current whole-polygon MPA/security screening before publication.
Do not delete an existing public cache merely to force adoption.

The scheduled publication already running on main predates these sources;
its progress cannot be credited to this batch. Next acquisition priority is the
remaining SCC native windows intersecting Conception r03 and the San Simeon
gaps, matched by inspected native footprints rather than cruise descriptions.
