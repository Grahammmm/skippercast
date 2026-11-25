# Python requirements, extras and workflow installs

| Question | Finding |
| --- | --- |
| Do the requirements files match? | Yes. There are **six** `requirements-*.txt` files. Each matches its namesake extra after following includes or self-references (`tests/contract/test_packaging.py:17–20,39–64,85–96`; R2). |
| Which Python runs the tests? | `ci.yml` uses **3.11 and 3.13** for the non-GIS matrix and **3.13** for both full-suite parts. Both research review workflows use **3.12**, including the jobs that install the survey file (`ci.yml:93–122,312–359`; `research-fish-survey.yml:10–469`; `research-substrate.yml:10–1495`; R1). |
| Do all workflow installs use the mirrors? | No. `advisor-media.yml:37` installs `[advisor]` directly, and the research workflows have standalone pins, some different from the survey stack (R1–R2). No checked-in workflow installs `[tls]` or `[fleet]` (R3). |
| Is everything locked? | No. The mirror checks direct Python pins, not build or transitive dependencies. Editable project installs allow `setuptools>=68` (`pyproject.toml:1–13`; `ci.yml:122,339`; `advisor-media.yml:37`); the media job also installs `ffmpeg` without a version (`advisor-media.yml:39`; R3). |

Evidence is from the staged `origin/main` at `34761911d5c44a903873867426f316c7f1e5911c`, read offline on 2026-11-21. Workflow citations in this report are relative to `.github/workflows/`. The table reports what the jobs request, not observed hosted runs: `3.13` selects a minor series, not a fixed patch; **runner Python** means the job invokes `python3` before or without a version setup and the exact version is not specified by the workflow. **None** means no Python invocation or install, as applicable, on the checked-in job path; it does not describe a hosted runner's preinstalled tools.

## R1. Workflows and interpreter choices

Names in the install column such as `survey` mean `requirements-survey.txt` (not `.[survey]`); brackets denote an actual extra install. Install lines are in the named workflow unless otherwise noted. The two research review workflows are split into a continuation table for readability.

| Workflow | Job(s) and declaration line | Python version and evidence | Direct Python installs |
| --- | --- | --- | --- |
| `advisor-media.yml` | `derive`:19 | 3.13 (:33) | Editable project with `[advisor]` (:37). |
| `basemap.yml` | `basemap`:27 | 3.13 (:39) | `publish`, `test` (:46). |
| `budget-drift.yml` | `drift`:25 | Runner Python (:26,43,63–64) | None. |
| `buoy-history.yml` | `history`:29 | 3.13 (:42) | `publish` (:46). |
| `ci.yml` | `changes`:41; `survey-science`:65 | Runner Python (:43,55–60; :73,92) | None. `survey-science` is the roll-up, not the science installer (:71–92). |
| `ci.yml` | `survey-tests`:93 (`coast`, `rest`:103) | 3.13 (:113) | Editable core project plus `survey`, `ocean`, `publish`, `test` (:122). |
| `ci.yml` | `e2e`:172; `e2e-2`:245; `e2e-3`:254; `e2e-4`:263; `e2e-flake-rates`:272 | None. The four browser jobs share the steps at :185–244 via :253,262,271; the flake report is a Node job (:272–311). | None. Browser jobs install locked web dependencies and Chromium with system libraries (:200–204). |
| `ci.yml` | `check`:312 | 3.11 and 3.13 (matrix :323, setup :336) | Editable core project (:339), `test` (:345), `ruff==0.17.5` (:400–403), on both legs. |
| `coast-assets.yml` | `publish`:28 | 3.13 (:43) | `publish` (:46). |
| `daily-data.yml` | `refresh`:35 | 3.13 (:49) | `sst`, `publish` (:55). |
| `dco.yml` | `sign-off`:38 | Runner Python (:39,89–91) | None. |
| `deploy-cloudflare.yml` | `source`:51; `deploy`:190; `report`:543; `rollback`:632 | Runner Python (`source`:74; `deploy`:252,262,316,469; `report`:572; `rollback`:681 → `scripts/smoke_test.sh:56`) | None in these four jobs; the deploy job installs locked web dependencies (:260). |
| `deploy-cloudflare.yml` | `stage_relief`:484 | Runner Python for the probe (:527), then 3.13 only if the probe reports staging is required (:528–531) | Conditional `.stage-controller/requirements-publish.txt` (:532–534), from the workflow's own revision (:512–524), not the candidate tree (:505–511). |
| `draft-region-health.yml` | `health`:19 | 3.13 (:34) | `sst` (:38). |
| `draft-region-rehearsal.yml` | `rehearse`:18 | 3.13 (:33) | `sst` (:37). |
| `e2e-timing.yml` | `timing`:23 | None (:23–83) | None; locked web dependencies and Chromium with system libraries (:35–40). |
| `feed-freshness.yml` | `check`:25 | 3.13 (:35) | None; the later install is locked web dependencies (:152). |
| `fleet-health.yml` | `check`:29 | None (job at :29 onward) | None, including no `[fleet]`. |
| `forecast-tiles.yml` | `build`:21 | 3.13 (:31) | `ocean`, `publish` (:36). |
| `live-conditions.yml` | `refresh`:23; `notify`:102 | 3.13 for each (:38 and :114) | `refresh`: `ocean`, `publish` (:44); `notify`: none (:102–121). |
| `live-conditions.yml` | `alarm-clock`:62; `next`:122 | None (:62–101,122 onward) | None. |
| `ops-report.yml` | `report`:22 | 3.13 (:34) | None (:22 onward). |
| `regional-legal-review.yml` | `packet`:25 | 3.13 (:39) | None (:25 onward). |
| `release.yml` | `release`:20 | Runner Python (:21,31) | None. |
| `research-daily.yml` | `inventory`:26 | 3.13 (:33) | `shapely==2.2.0` (:35). |
| `seafloor.yml` | `prepare`:47; `reaches`:94; `publish`:123; `ledger`:207 | 3.13 in all four (:61,108,139,220) | `seafloor` in all four (:64,111,142,223); includes `survey`, `publish`, `test` (`requirements-seafloor.txt:2–4`). |

| Workflow | Job(s) | Python version and setup line | Direct Python installs |
| --- | --- | --- | --- |
| `research-fish-survey.yml` | `nos-historic-seabed-gap`, `central-rov-deep-reference` | 3.12 (:17,319 respectively) | `pyproj==3.7.1 shapely==2.1.2` (:19,321). |
| `research-fish-survey.yml` | `estero-original-depth-and-independent-character` | 3.12 (:69) | `numpy==2.2.6 scipy==1.17.1 rasterio==1.4.3 pyproj==3.7.1 shapely==2.1.2 pyshp==2.3.1` (:71). |
| `research-fish-survey.yml` | `point-buchon-original-pair` | 3.12 (:182) | `numpy==2.2.6 rasterio==1.4.3 pyproj==3.7.1 shapely==2.1.2 pyshp==2.3.1 pypdf==6.10.0` (:184). |
| `research-fish-survey.yml` | `noaa-vdatum-monterey-coverage` | 3.12 (:403) | `shapely==2.1.2` (:405). |
| `research-fish-survey.yml` | `central-dataone-rov-spot-precision`, `ccfrp-open-reference-context`, `central-300-research-priority`, `cdfw-crfs-historical-rcgl`, `cdfw-crfs-all-species-baseline`, `noaa-dismap-groundfish` | 3.12 (:40,357,380,427,448,469 respectively) | None in these six jobs. |
| `research-substrate.yml` | `monterey-original-300-source-screen`, `monterey-original-multibeam-crosssurvey`, `central-coverage-and-source-queue`, `san-pedro-original-character`, `original-hard-context-enc-review`, `bluetopo-source-leads`, `usgs-caldig-deepwater` | 3.12 (:17,93,208,383,555,694,733 respectively) | `survey` (:19,95,210,385,557,696,735 respectively). |
| `research-substrate.yml` | `csumb-native`, `central-deepwater`, `san-miguel-original-habitat`, `audit`, `hard-footprint-native-depth`, `usgs-sur-arguello-sediment`, `h11983-original-point-st-george`, `usgs-ds781-native-character` | 3.12 (:798,815,851,922,1294,1335,1395,1493 respectively) | `survey` (:800,817,853,924,1296,1337,1397,1495 respectively). |
| `research-substrate.yml` | `usgs-state-waters-catalog`, `nos-historical-seabed-samples`, `reefcheck-historical-observations`, `ncei-survey-discovery`, `csumb-scc-source-leads` | 3.12 (:470,505,527,764,1358 respectively) | None in these five jobs. |

The package floor is `>=3.11` with no mandatory runtime dependencies (`pyproject.toml:10–13`; `CONTRIBUTING.md:17`). The survey note says 3.12+ in CI, but neither the extra nor the file declares a Python-version marker for those pins (`pyproject.toml:22–38`; `requirements-survey.txt:1–18`). The file's “CI: 3.13” describes the main full-suite job, not every consumer: the substrate workflow also installs that exact file on 3.12 (R1). `CONTRIBUTING.md:24–25` and `docs/engineering/testing.md:18–24` show local extra-based equivalents; the actual full-suite install is in `survey-tests`, and the `survey-science` job only checks results (`ci.yml:65–122`).

## R2. Package-by-package pin comparison

Every version in the two middle columns is an exact `==` pin and applies to every declaration cited in the cell. File labels abbreviate `requirements-<label>.txt`; extra line numbers point to `pyproject.toml`. The rows list direct declarations; apply the two expansion rules below the table to read inherited membership. “Match?” compares the file and extra pins, not the standalone workflow pins in the last column. A dash means no declaration in that column.

| Package | Requirements file pins | Extra pins | Match? | Standalone workflow pin(s) |
| --- | --- | --- | --- | --- |
| `affine` | `3.0.1` survey:11 | `3.0.1` survey:30 | Yes | — |
| `boto3` | `1.44.3` publish:2 | `1.44.3` publish:41 | Yes | — |
| `eccodes` | `2.50.1` ocean:5 | `2.50.1` ocean:19 | Yes | — |
| `h5py` | `3.16.0` survey:10 | `3.16.0` survey:29 | Yes | — |
| `jsonschema` | `4.26.0` survey:18, publish:5, test:5 | `4.26.0` survey:37, publish:41, test:44, fleet:54 | Yes | — |
| `laspy[lazrs]` | `2.7.0` survey:15 | `2.7.0` survey:34 | Yes | — |
| `lazrs` | `0.8.2` survey:16 | `0.8.2` survey:35 | Yes | — |
| `moto` | `5.2.5` test:11 | `5.2.5` test:44 | Yes | — |
| `netCDF4` | `1.7.5.1.post1` ocean:3 | `1.7.5.1.post1` ocean:19 | Yes | — |
| `numpy` | `2.5.3` ocean:2, sst:2, survey:5 | `2.5.3` ocean:19, sst:21, survey:24 | Yes | `2.2.6` fish survey :71,184 (different) |
| `Pillow` | — | `13.0.0` advisor:51 | N/A (no file pin) | — |
| `pillow-heif` | — | `1.8.1` advisor:51 | N/A (no file pin) | — |
| `pylerc` | `4.3.0` survey:12 | `4.3.0` survey:31 | Yes | — |
| `pypdf` | `7.1.0` survey:14 | `7.1.0` survey:33 | Yes | `6.10.0` fish survey :184 (different) |
| `pyproj` | `3.8.0` survey:9 | `3.8.0` survey:28 | Yes | `3.7.1` fish survey :19,71,184,321 (different) |
| `pyshp` | `3.1.8` survey:13 | `3.1.8` survey:32 | Yes | `2.3.1` fish survey :71,184 (different) |
| `pytest` | `9.2.0` test:7 | `9.2.0` test:44 | Yes | — |
| `pytest-xdist` | `3.8.0` test:9 | `3.8.0` test:44 | Yes | — |
| `rasterio` | `1.5.1` survey:7 | `1.5.1` survey:26 | Yes | `1.4.3` fish survey :71,184 (different) |
| `ruff` | — | `0.17.5` dev:56 | N/A (no file pin) | `0.17.5` `ci.yml:402` (same as extra) |
| `scipy` | `1.17.1` ocean:4, sst:3, survey:6 | `1.17.1` ocean:19, sst:21, survey:25 | Yes | `1.17.1` fish survey :71 (same) |
| `shapely` | `2.2.0` survey:8 | `2.2.0` survey:27 | Yes | `2.2.0` `research-daily.yml:35` (same); `2.1.2` fish survey :19,71,184,321,405 (different) |
| `truststore` | — | `0.10.5` tls:48 | N/A (no file pin) | — |
| `zstandard` | `0.25.0` test:13 | `0.25.0` test:44, fleet:54 | Yes | — |

“Fish survey” in the last column is `research-fish-survey.yml`. Expansion rules:

- `requirements-seafloor.txt:2–4` includes the `survey`, `publish` and `test` file pins above, at those same versions. The `seafloor` extra includes the same three extras (`pyproject.toml:46`). Neither declares a package version of its own.
- `dev` includes all pins in `ocean`, `survey`, `publish`, `test`, `tls` and `advisor` plus Ruff (`pyproject.toml:56`). It does not name `fleet`, `sst` or `seafloor`, but receives every pin in those groups through the named extras (compare `pyproject.toml:19–56`). It has no `requirements-dev.txt`.

The contract checks that the six file names exactly equal `MIRRORED`, compares expanded pin sets, and requires exact pins for non-self dependencies of every extra (`tests/contract/test_packaging.py:17–20,39–64,85–101`). It does not compare inline workflow pins or resolve transitive dependencies. Thus the fish-survey differences are not failures of the six mirrors. There is no separate seventh requirements file in the tracked inventory below.

## R3. Extras without files and unpinned installs

| Extra without a namesake file | Workflow use |
| --- | --- |
| `tls` (`pyproject.toml:47–48`) | None, directly or via `dev`. `truststore` is optional; no workflow requests it in the install inventory. |
| `advisor` (`pyproject.toml:49–51`) | `advisor-media.yml:37` installs `-e ".[advisor]"` on 3.13 (:33). |
| `fleet` (`pyproject.toml:52–54`) | None, despite the TOML comment. `fleet-health.yml:29` onward checks fleet health without installing the extra; its two package pins are available separately through `test` (`pyproject.toml:44,54`). |
| `dev` (`pyproject.toml:55–56`) | None. `ci.yml:402` installs its Ruff pin directly, not the extra. |

- **Python:** No versionless direct third-party Python package name is passed to `pip install` in the workflow inventory. `ci.yml:122,339` and `advisor-media.yml:37` install the checked-out project, so the first-party source is set by checkout rather than a registry `==` pin (project version at `pyproject.toml:7`). Those commands do not disable build isolation, and the project's build requirement `setuptools>=68` is a lower bound, not an exact version (`pyproject.toml:1–3`). Exact direct requirements are not a full lock of what pip may resolve.
- **Other packages/tools:** `advisor-media.yml:39` uses `apt-get install ... ffmpeg` without a version. `ci.yml:204` and `e2e-timing.yml:40` ask Playwright to install Chromium with system dependencies; no OS package versions are specified by those commands (the preceding JavaScript dependency install is frozen). This is separate from the Python pins. Basemap's Go tool is specified as `go-pmtiles@v1.31.2` (`basemap.yml:48`) and the deploy command specifies `wrangler@4.142.0` (`deploy-cloudflare.yml:48`).

## R4. One possible follow-up, no change proposed here

**Docs-only, estimated 30–45 minutes:** clarify `requirements-survey.txt:2` to distinguish the 3.13 full-suite job (`ci.yml:113,122`) from 3.12 research consumers (`research-substrate.yml:17,19`), and clarify `pyproject.toml:53` to say no checked-in workflow installs `[fleet]`. Only those two files would be in scope. Test offline in an already prepared checkout: `python -m pytest -q tests/contract/test_packaging.py::ExtrasTests::test_every_requirements_file_matches_its_extra tests/contract/test_packaging.py::ExtrasTests::test_every_pin_is_exact` and `python scripts/check_repository.py`. No dependency pin, workflow, Python version or policy change is needed for those clarifications.

### Reproduce the source reads

From a checkout with the pinned commit, the following inventory commands work offline (replace `origin/main` with the SHA at the top if the ref has moved). `git grep -n '^' <ref> -- <path>` shows the complete numbered source for any cited file. Inspect the `jobs:` section as a whole, including shared YAML steps and invoked scripts; a match in comments or `cache-dependency-path` is not an install.

```sh
git rev-parse origin/main
git ls-tree -r --name-only origin/main -- .github/workflows 'requirements-*.txt'
git grep -nE 'python-version:|python: \[|python3?|pip|install|steps: \*' origin/main -- .github/workflows
git grep -n '^' origin/main -- 'requirements-*.txt' pyproject.toml tests/contract/test_packaging.py
git grep -nE 'pip install|3\.11|3\.13|survey-science|survey-tests' origin/main -- CONTRIBUTING.md docs/engineering/testing.md
```
