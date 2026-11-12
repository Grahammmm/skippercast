# MGL-05 — private legal-screen refresh receipt

**REVIEW-REQUIRED. Never the only check, never a legal clearance, never used for a ledger write or publication. Not fishing/navigation advice.**

Outcome: **COMPLETE**

## Run receipt

| main SHA | private root | UTC start | UTC end | CLI | rc | elapsed s | logs | outcome | attempts |
|---|---|---|---|---|---|---|---|---|---|
| 43489ec3701abb03b8294cd357ef5d6f2cae1e8f | /home/user/agent-work/reports/seafloor-agg/private-runs/MGL-05 | 2026-11-12T16:10:51.993969+00:00 | 2026-11-12T16:11:26.026625+00:00 | `/home/user/repos/skippercast/.venv/bin/python -B /home/user/agent-work/bin/seafloor-cli.py --checkout /home/user/agent-work/reports/seafloor-agg/private-runs/MGL-05/repo refresh-screen` | 0 | 34.03 | /home/user/agent-work/reports/seafloor-agg/private-runs/MGL-05/logs/refresh.stdout, refresh.stderr | COMPLETE | 1 |

Offline baseline tests (run before refresh): test-screen: 15 passed, 98 warnings, 18 subtests passed in 0.47s; test-collect: 25 passed, 49 subtests passed in 0.21s

Note: source worktree HEAD at prepare was 9bc6ffd6028c3f83a7d37d1aa67af08c9ab69a00 (moved past the spec's pinned commit); the run used the committed bytes of 43489ec3701abb03b8294cd357ef5d6f2cae1e8f via git archive.

## Snapshot
| path | actual SHA256 | checked_at | age | version | policy SHA | scope | reviewed_reaches |
|---|---|---|---|---|---|---|---|
| /home/user/agent-work/reports/seafloor-agg/private-runs/MGL-05/repo/var/seafloor/screen/snapshot.json | 6de012f8af3d972716297a1d50340e4c9ef30159ae5003292256d4bc38873c2e | 2026-11-12T16:11:25.845248+00:00 | age 0.000 d; fresh | whole-polygon-screen-v1 | agree | {"type": "Polygon", "coordinates": [[[-120.45, 34.4], [-120.45, 36.62], [-122.1,... | big-sur-coast-r01,big-sur-coast-r02,big-sur-coast-r03,big-sur-coast-r04,big-sur-coast-r05,big-sur-coast-r06,cambria-san-simeon-r01,cambria-san-simeon-r02,monterey-point-sur-r01,monterey-point-sur-r02,monterey-point-sur-r03,monterey-point-sur-r04,morro-bay-r01,morro-bay-r02,morro-bay-r03,morro-bay-r04,morro-bay-r05,morro-bay-r06,morro-bay-r07,morro-bay-r08,morro-bay-r09,morro-bay-r10,point-arguello-conception-r01,point-arguello-conception-r02,point-arguello-conception-r03,point-arguello-conception-r04,point-arguello-conception-r05,point-arguello-conception-r06,point-arguello-conception-r07,point-arguello-conception-r08,south-big-sur-san-simeon-r01,south-big-sur-san-simeon-r02,south-big-sur-san-simeon-r03 |

## Layers
| layer | source URL | artifact | recorded SHA256 | recomputed SHA256 | checked_at | recorded count | actual count | status | filename token (not a hash substitute) |
|---|---|---|---|---|---|---|---|---|---|
| cdfw-mpa | https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query?where=1%3D1&outFields=NAME%2CFULLNAME%2CType%2CCCR&returnGeometry=true&outSR=4326&f=geojson&resultRecordCount=1000 | cdfw-mpa-e470c41f16331e0262bf005f7634b4823885ded6ba39a0410e072dc24ac76b12.json | 14487293226530005f64f0a628c4872382c291e1df36ea492cb0223e6b696b41 | 14487293226530005f64f0a628c4872382c291e1df36ea492cb0223e6b696b41 | 2026-11-12T16:10:52.516506+00:00 | 155 | 155 | OK | e470c41f1633 |
| noaa-federal | https://maps.fisheries.noaa.gov/server/rest/services/WCR_SFD_GCA/NOAA_Fisheries_West_Coast_Region_Groundfish_Conservation_Area_service/MapServer | noaa-federal-50c1bb0ec0867dc75a4d4e27041096e21a39ca28a6702608230690c7595f330a.json | e5b8a9ce9708895af93a61cc53981244b990cf3af1bef913c7c5b745e064d859 | e5b8a9ce9708895af93a61cc53981244b990cf3af1bef913c7c5b745e064d859 | 2026-11-12T16:10:54.296165+00:00 | 29 | 29 | OK | 50c1bb0ec086 |
| security | https://www.ecfr.gov/api/versioner/v1/full/2026-11-09/title-33.xml?section=165.1155 | security-b9d7ead758ba5c1ef379bcc5495fc9e8d377e5326656ed7293a52b88feac4258.json | 7fdb254e84aa45587cff2773417af92a2d933fad70fab1c8466bdbfe88249a12 | 7fdb254e84aa45587cff2773417af92a2d933fad70fab1c8466bdbfe88249a12 | 2026-11-12T16:11:25.845248+00:00 | 3 | 3 | OK | b9d7ead758ba |

eCFR: {"up_to_date_as_of": "2026-11-09", "sections": [["https://www.ecfr.gov/api/versioner/v1/full/2026-11-09/title-33.xml?section=165.1155", "5b95cac2ee51b8343f8dda71d9159db1430cb2c4fbd82cc6e36ce775e7f8cb18", null], ["https://www.ecfr.gov/api/versioner/v1/full/2026-11-09/title-33.xml?section=334.1130", "637990c375cd4b039cf03f97d38d98a1773a331a8c961ca61a5dcdf29987c541", null], ["https://www.ecfr.gov/api/versioner/v1/full/2026-11-09/title-33.xml?section=165.1196", "c92807fb35bb435c33f02309ed9e821bd963cb9da6da12dcef68b81165c8121f", null], ["https://www.ecfr.gov/api/versioner/v1/full/2026-11-09/title-33.xml?section=334.1150", "0e49862e6dd76e8c7e52bbddb84b09878d5a0851a389d329dedeea6dfb69ef9d", "outside-reviewed-scope"], ["https://www.ecfr.gov/api/versioner/v1/full/2026-11-09/title-33.xml?section=165.1183", "0a7a7bd6183ba6ed075c121cb712329bb7842ef741af4ee3cc0dd4bdd8e0cfe5", "trip-time-vessel-restriction"]]}

## Committed inventory (from 43489ec370)
| path | SHA256 | feature count |
|---|---|---|
| dist/data/protected-areas.geojson | 508354c45c1875718ed5badeb9450140dd8fbdbdf71a8e35e29a21889c67ed72 | 8 |
| dist/regions/big-sur-coast/protected-areas.geojson | 96bae067ce8ef84a72272ad765c81b9dffecc4ae3ec2a24d9790aad787411ef6 | 4 |
| dist/regions/monterey-point-sur/protected-areas.geojson | a1f715d1471016e8287de84a35de19a56805ae41b82eb181b244e6cdde900f91 | 9 |
| dist/regions/point-arena-bodega/protected-areas.geojson | 9c36fee1babbaf21ae9886a646067e1fa3695ab6e4fcad5502883e4145a4dc3b | 11 |
| dist/regions/point-arguello-conception/protected-areas.geojson | 729f9de93f824eb3455a8d3b0e4ebb356b97c64d76f05afc76d313bde7495cb6 | 2 |
| dist/regions/point-reyes-pigeon/protected-areas.geojson | 24861d66c20ce905106c5b55a397c38fcf085dd97a0436d036bae5422201aa9c | 14 |
| dist/regions/santa-cruz-monterey-bay/protected-areas.geojson | d53ce9b39ef4722c04b0c118ef868e47b381cf37809fb9dd85a7bd32e4addbcd | 12 |
| dist/regions/shelter-cove-north-mendocino/protected-areas.geojson | c9f8d1347cb7583f14a6573b50ed0d59b91b58744d017b04506ea7d3c9a30b02 | 7 |
| dist/regions/south-big-sur-san-simeon/protected-areas.geojson | 1505ca582653b62055e8717bb30b584ba853f4c6742db64cc730b9e0165d8227 | 2 |
| dist/regions/southern-california/protected-areas.geojson | b1a8feed6203baadd703515516816b25b0df0f4dfd0cde58448bbb30719011bb | 61 |
| dist/data/noaa-federal-areas.json | 14d5f521420aeea8557eaaba63ba14860a0a1b2e8c6ea3d426957658428813d9 | 29 (retrieved_at 2026-09-23T22:56:33.483262+00:00) |

CDFW raw sum 130; deduplicated union 122 by canonical full-feature JSON SHA256 (content-identity proxy; committed files carry no stable feature ID, only NAME/FULLNAME/Type/CCR); distinct NAME 122; NAMEs with conflicting geometries 0. Regional inventories overlap; the raw sum is not a unique count.

## Comparison
| layer | RUN-3 historical | measured committed | refreshed count | delta vs dedup/committed | aligned | caveat |
|---|---|---|---|---|---|---|
| cdfw-mpa | RUN-3: 122 cached vs 155 live (2026-11-10) | raw sum 130; dedup 122; distinct NAME 122 | 155 | 33 | NAME-aligned (no stable ID in committed files): common 122, added 33, removed 0; full-feature identity common 120 | content-identity proxy; NAME duplicates with differing geometry: 0; refreshed property keys differ -> count-only comparison insufficient |
| noaa-federal | n/a | 29 (retrieved 2026-09-23T22:56:33.483262+00:00) | 29 | 0 | N/A | refreshed file shape differs from committed wrapper; counts only |
| security | n/a | no committed protected-area equivalent | 3 | N/A | N/A | compare eCFR hashes: {"up_to_date_as_of": "2026-11-09", "sections": [["https://www.ecfr.gov/api/versioner/v1/full/2026-11-09/title-33.xml?section=165.1155", "5b95cac2ee51b8343f8dda71d9159db1430cb2c4fbd82cc6e36ce775e7f8cb18", null], ["https://www.ecfr.gov/api/versioner/v1/full/2026-11-09/title-33.xml?section=334.1130", "637990c375cd4b039cf03f97d38d98a1773a331a8c961ca61a5dcdf29987c541", null], ["https://www.ecfr.gov/api/versioner/v1/full/2026-11-09/title-33.xml?section=165.1196", "c92807fb35bb435c33f02309ed9e821bd963cb9da6da12dcef68b81165c8121f", null], ["https://www.ecfr.gov/api/versioner/v1/full/2026-11-09/title-3 |

Historical 122/155 is context only; neither is a forced expected count. Inventory drift is not diagnosed here as to polygon effect or provenance.

## Scope / holds (screen.load_snapshot per committed reach)
| reach | status | reasons |
|---|---|---|
| morro-bay-r04 | ready | - |
| morro-bay-r03 | ready | - |
| morro-bay-r05 | ready | - |
| morro-bay-r02 | ready | - |
| morro-bay-r06 | ready | - |
| morro-bay-r01 | ready | - |
| morro-bay-r07 | ready | - |
| cambria-san-simeon-r02 | ready | - |
| morro-bay-r08 | ready | - |
| cambria-san-simeon-r01 | ready | - |
| morro-bay-r09 | ready | - |
| morro-bay-r10 | ready | - |
| south-big-sur-san-simeon-r03 | ready | - |
| point-arguello-conception-r01 | ready | - |
| south-big-sur-san-simeon-r02 | ready | - |
| point-arguello-conception-r02 | ready | - |
| south-big-sur-san-simeon-r01 | ready | - |
| point-arguello-conception-r03 | ready | - |
| big-sur-coast-r06 | ready | - |
| point-arguello-conception-r04 | ready | - |
| big-sur-coast-r05 | ready | - |
| point-arguello-conception-r05 | ready | - |
| big-sur-coast-r04 | ready | - |
| point-arguello-conception-r06 | ready | - |
| big-sur-coast-r03 | ready | - |
| point-arguello-conception-r07 | ready | - |
| big-sur-coast-r02 | ready | - |
| point-arguello-conception-r08 | ready | - |
| big-sur-coast-r01 | ready | - |
| monterey-point-sur-r04 | ready | - |
| monterey-point-sur-r03 | ready | - |
| monterey-point-sur-r02 | ready | - |
| monterey-point-sur-r01 | ready | - |
| santa-cruz-monterey-bay-r13 | held | screen-scope-unreviewed |
| santa-cruz-monterey-bay-r12 | held | screen-scope-unreviewed |
| santa-cruz-monterey-bay-r11 | held | screen-scope-unreviewed |
| santa-cruz-monterey-bay-r10 | held | screen-scope-unreviewed |
| santa-cruz-monterey-bay-r09 | held | screen-scope-unreviewed |
| santa-cruz-monterey-bay-r08 | held | screen-scope-unreviewed |
| santa-cruz-monterey-bay-r07 | held | screen-scope-unreviewed |
| santa-cruz-monterey-bay-r06 | held | screen-scope-unreviewed |
| santa-cruz-monterey-bay-r05 | held | screen-scope-unreviewed |
| santa-cruz-monterey-bay-r04 | held | screen-scope-unreviewed |
| santa-cruz-monterey-bay-r03 | held | screen-scope-unreviewed |
| santa-cruz-monterey-bay-r02 | held | screen-scope-unreviewed |
| santa-cruz-monterey-bay-r01 | held | screen-scope-unreviewed |

No legal clearance inferred; H6 per-reach human security-zone review still required.

## Integrity / failure
| file | frozen SHA256 | SHA256 at finish |
|---|---|---|
| dist/data/seafloor-ledger.json | ad550087f443ed7098216b09461bbd7d551206a43370a644b3c00d5956764848 | ad550087f443ed7098216b09461bbd7d551206a43370a644b3c00d5956764848 |
| catalog/reaches.json | 2e53b7fac0228df00cf6eaeef5fc30297d3788c4ef4f880425351ab2f03d5777 | 2e53b7fac0228df00cf6eaeef5fc30297d3788c4ef4f880425351ab2f03d5777 |
| catalog/seafloor-screen.json | ed7f16c3119b440271964615a07a338134d653e00e9f3662be05a8ce680dd2de | ed7f16c3119b440271964615a07a338134d653e00e9f3662be05a8ce680dd2de |
| dist/data/noaa-federal-areas.json | 14d5f521420aeea8557eaaba63ba14860a0a1b2e8c6ea3d426957658428813d9 | 14d5f521420aeea8557eaaba63ba14860a0a1b2e8c6ea3d426957658428813d9 |
| dist/data/protected-areas.geojson | 508354c45c1875718ed5badeb9450140dd8fbdbdf71a8e35e29a21889c67ed72 | 508354c45c1875718ed5badeb9450140dd8fbdbdf71a8e35e29a21889c67ed72 |
| dist/regions/big-sur-coast/protected-areas.geojson | 96bae067ce8ef84a72272ad765c81b9dffecc4ae3ec2a24d9790aad787411ef6 | 96bae067ce8ef84a72272ad765c81b9dffecc4ae3ec2a24d9790aad787411ef6 |
| dist/regions/monterey-point-sur/protected-areas.geojson | a1f715d1471016e8287de84a35de19a56805ae41b82eb181b244e6cdde900f91 | a1f715d1471016e8287de84a35de19a56805ae41b82eb181b244e6cdde900f91 |
| dist/regions/point-arena-bodega/protected-areas.geojson | 9c36fee1babbaf21ae9886a646067e1fa3695ab6e4fcad5502883e4145a4dc3b | 9c36fee1babbaf21ae9886a646067e1fa3695ab6e4fcad5502883e4145a4dc3b |
| dist/regions/point-arguello-conception/protected-areas.geojson | 729f9de93f824eb3455a8d3b0e4ebb356b97c64d76f05afc76d313bde7495cb6 | 729f9de93f824eb3455a8d3b0e4ebb356b97c64d76f05afc76d313bde7495cb6 |
| dist/regions/point-reyes-pigeon/protected-areas.geojson | 24861d66c20ce905106c5b55a397c38fcf085dd97a0436d036bae5422201aa9c | 24861d66c20ce905106c5b55a397c38fcf085dd97a0436d036bae5422201aa9c |
| dist/regions/santa-cruz-monterey-bay/protected-areas.geojson | d53ce9b39ef4722c04b0c118ef868e47b381cf37809fb9dd85a7bd32e4addbcd | d53ce9b39ef4722c04b0c118ef868e47b381cf37809fb9dd85a7bd32e4addbcd |
| dist/regions/shelter-cove-north-mendocino/protected-areas.geojson | c9f8d1347cb7583f14a6573b50ed0d59b91b58744d017b04506ea7d3c9a30b02 | c9f8d1347cb7583f14a6573b50ed0d59b91b58744d017b04506ea7d3c9a30b02 |
| dist/regions/south-big-sur-san-simeon/protected-areas.geojson | 1505ca582653b62055e8717bb30b584ba853f4c6742db64cc730b9e0165d8227 | 1505ca582653b62055e8717bb30b584ba853f4c6742db64cc730b9e0165d8227 |
| dist/regions/southern-california/protected-areas.geojson | b1a8feed6203baadd703515516816b25b0df0f4dfd0cde58448bbb30719011bb | b1a8feed6203baadd703515516816b25b0df0f4dfd0cde58448bbb30719011bb |
| baseline/dist/data/seafloor-ledger.json | ad550087f443ed7098216b09461bbd7d551206a43370a644b3c00d5956764848 | ad550087f443ed7098216b09461bbd7d551206a43370a644b3c00d5956764848 |
| baseline/catalog/reaches.json | 2e53b7fac0228df00cf6eaeef5fc30297d3788c4ef4f880425351ab2f03d5777 | 2e53b7fac0228df00cf6eaeef5fc30297d3788c4ef4f880425351ab2f03d5777 |

Drift: NONE. Private ledger == baseline ledger and reaches == baseline reaches: yes. Source status before/after: '' / ''. Source HEAD before/after: 9bc6ffd6028c3f83a7d37d1aa67af08c9ab69a00 / 9bc6ffd6028c3f83a7d37d1aa67af08c9ab69a00.
