# SCB-07-C: read-only regional control probe

Probed at 2026-11-14T16:37:07.753771+00:00 against the existing public service host using curl GETs.
No workflow, engine, screen refresh or publishing step was run.

| Region / control | HTTP | Status | expires_at | Full export bytes | Slim bytes |
| --- | --- | --- | --- | ---: | ---: |
| [morro-bay](https://skippercast.g4651.workers.dev/feeds/tiles/seafloor/manifest-morro-bay.json) | 200 | ready | `2026-12-15T00:00:00+00:00` | 15458263 | 363464 |
| [cambria-san-simeon](https://skippercast.g4651.workers.dev/feeds/tiles/seafloor/manifest-cambria-san-simeon.json) | 200 | ready | `2026-12-15T00:00:00+00:00` | 1001095 | 45749 |
| [monterey-point-sur](https://skippercast.g4651.workers.dev/feeds/tiles/seafloor/manifest-monterey-point-sur.json) | 200 | ready | `2026-12-15T00:00:00+00:00` | 4450350 | 128825 |
| [point-arguello-conception](https://skippercast.g4651.workers.dev/feeds/tiles/seafloor/manifest-point-arguello-conception.json) | 200 | ready | `2026-12-15T00:00:00+00:00` | 8364381 | 189018 |

Earliest expiry: `2026-12-15T00:00:00+00:00`. These are dated observations, not ongoing release approval.

The normal brief loads only the selected region's existing hash-verified slim export (full export only under its existing fallback). The gate adds four small control reads, not four region exports.

Python urllib probes were refused with HTTP 403 on both the custom domain and service host. curl against the service host succeeded for all four controls. No credentials, edge settings or access rules were changed.

Source use remains noncommercial and monetization remains none, as directed by G. This observation does not supply the separate human monthly zone attestation or authorize a new source, rights approval or baseline pin.
