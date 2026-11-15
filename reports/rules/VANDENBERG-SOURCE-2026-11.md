# Held Vandenberg maritime source: why it cannot be fetched, and official alternatives (2026-11)

Report only (SC1114-08). It changes no registry, allowed-host list, region or review file, and it **does not approve any source**. A replacement needs G's signature.

- Checked main: `f8a679d1451141ccad443d65d5138a0cbb6e3074` (clean clone of `origin/main`).
- Observed: 2026-11-15 20:32 UTC, Python 3.12.3 (repo venv), package `SkipperCast/0.8.0`. The probe asserted `skippercast.http` was imported from the clone's `src/`. No config overrides, no cache, no credentials.
- Held source: `jurisdictions/california-central.json:162-168`, id `access-vandenberg-maritime`, URL `https://www.vandenberg.spaceforce.mil/About-Us/Environmental/Vandenberg-SFB-Maritime-Updates/`, keywords `Danger Zone 4` and `Vessel Safety Areas`. Review row: `jurisdictions/reviews/2026-11-14-california-central.json:116-119` (`"decision": "hold"`, `"content_sha256": null`, note: unfetched row stays on hold, as G signed 2026-11-14 07:10).

## 1. What a plain GET returns today

Method: the pipeline's own `collect.Client.get` on a `skippercast.http.Session` built with `http.default_allowlist(root=clone)` and `cache=None`. A thin subclass overrode `_hop` only to record each hop and body. Nothing in the transport, TLS, header or allowlist path was changed. The probe was a scratch script outside the repo, run as `python3 -B probe_vandenberg.py <out-dir>` from the clone.

Settings in force (`src/skippercast/pipeline/collect.py:59-71,106-141`, `src/skippercast/http.py:71,73-77`): `Accept: */*`, `Accept-Encoding: gzip`, 25 s timeout, 5,000,000-byte cap, up to 2 attempts (retry on 429, 5xx and transport errors; not on 403), User-Agent `SkipperCast/0.8.0 (+https://skippercast.com)`, verified TLS, up to 10 redirects with every target rechecked against the allowlist.

| Observation | Result |
| --- | --- |
| Host admitted | yes, `www.vandenberg.spaceforce.mil` (allowed via `jurisdictions/california-central.json:164`, built in `http.py:257-279`) |
| Request | 1 attempt, `GET` on the exact held URL |
| Status | **403** |
| Redirects | none (final URL equals request URL) |
| Content type | `text/html`, content-length 470 (Client receipt shows `content_type: null`, because error rows do not store it; the header comes from the recorded hop) |
| Server | `AkamaiGHost` |
| Retry | none (403 is not retried) |
| Result | `HTTPStatusError: HTTP 403 from www.vandenberg.spaceforce.mil`, no receipt hash, `content_sha256` stays null |
| Elapsed | 415 ms |

Body of the 403 (complete):

```text
<TITLE>Access Denied</TITLE> <H1>Access Denied</H1>
You don't have permission to access "http://www.vandenberg.spaceforce.mil/About-Us/Environmental/Vandenberg-SFB-Maritime-Updates/" on this server.
Reference #18.ce06d217.1794774727.551df677
https://errors.edgesuite.net/18.ce06d217.1794774727.551df677
```

Diagnosis, kept to what was observed:

- This is a fetch failure at the edge, not a parser or content failure. The host is already allowed, TLS verified, the server answered, and Akamai's "Access Denied" page (an `errors.edgesuite.net` reference) was returned instead of the notice page. The keyword check and `page_watch` never ran.
- It is a bot wall of the plain-403 kind. It is not a JavaScript challenge, a login page, a 200 challenge or a redirect refusal.
- The probe matches the historical unfetched record (`content_sha256: null`). One observation cannot show the server's reason, whether this client's User-Agent or address, or whether the block is permanent. The pipeline rule forbids a browser, challenge solver or different User-Agent, so none was tried.
- A search-engine snippet (a different client, not inspected page content) shows the real page does exist and describes both topics: "Danger Zone 4 is always closed", "Vessel Safety Areas ... strictly prohibited zones". That is not evidence this pipeline can read it.
- The non-`www` form `vandenberg.spaceforce.mil` is not on the allowlist (`DisallowedHost`, no request sent), so it is not a repo-side workaround.

## 2. Official pages that carry danger-zone or vessel-safety notices

All were fetched with the same probe, except where marked. "Both keywords" means both literal phrases (case-insensitive) in the page content the Client returned. Static regulation and operational notice are different roles; no static page here is launch clearance.

| # | URL | Host | Admitted today? (file:line) | Both keywords? | Cadence |
| --- | --- | --- | --- | --- | --- |
| 1 | `https://www.ecfr.gov/api/versioner/v1/full/2026-09-28/title-33.xml?section=334.1130` (33 CFR 334.1130, the Vandenberg danger-zone rule, published by the Federal Register/GPO) | `www.ecfr.gov` | Yes. `EXTRA_HOSTS` at `src/skippercast/http.py:86`; also named in config at `jurisdictions/california-central.json:118` | **No, one of two.** `Danger Zone 4`: yes. `Vessel Safety Areas`: no. 200, `text/xml`, 10,581 chars, text states the Zone 4 no-stopping rule. `page_watch` rejects it for the missing second phrase. | Static law; changes only by rulemaking, no schedule published, observed once: **unknown** |
| 2 | `https://www.govinfo.gov/content/pkg/CFR-2024-title33-vol3/pdf/CFR-2024-title33-vol3-sec334-1130.pdf` (same section, CFR annual edition; the 2023 edition also returned 200) | `www.govinfo.gov` | Yes, via a config URL on that host: `jurisdictions/california-southern.json:206` (`http.py:257-279`). The bare `authority_hosts` entry at `california-central.json:258` does not count, since the regex only matches `https://` URLs. | **Unknown.** 200 `application/pdf`, but `Client.get` raised `UnicodeDecodeError` (PDF is not UTF-8). The current pipeline cannot read it. | Annual edition, per the 2023/2024 file names; unknown otherwise |
| 3 | `https://www.ecfr.gov/current/title-33/chapter-II/part-334/subpart-B/section-334.1130` (eCFR HTML page, the form the registry uses elsewhere) | `www.ecfr.gov` | Yes (as #1) | **Unknown.** Returned **302** to `https://unblock.federalregister.gov`, a host not on the allowlist, so the pipeline refused the hop (`DisallowedHost`). It is a bot wall on this client; the HTML page is not usable. #1 (API form) works. | Unknown |
| 4 | `https://navcen.uscg.gov/broadcast-notice-to-mariners-message?guid=69558960` (USCG Broadcast Notice to Mariners; a Vandenberg launch hazard message dated Aug 2026) | `navcen.uscg.gov` | **No.** Negative: `http.default_allowlist(root=clone).allows("navcen.uscg.gov")` is false; no https URL on this host in `catalog/sources.json`, `catalog/coasts.json`, `regions/*/region.json` or `jurisdictions/*.json`, and it is not in `EXTRA_HOSTS` (`http.py:84-98`). (`www.navcen.uscg.gov` appears bare at `catalog/sources.json:1250` and is also not admitted.) | **Unknown.** Not fetched by the pipeline (host refused, no request sent). A search snippet showed launch hazard text and "Frontier Control", with neither literal phrase. A separate fetcher got HTTP 403. | Event-driven, one notice per launch window; not a fixed schedule |

Not listed as candidates: the NGA NAVAREA XII warnings and the USCG Local Notice to Mariners. Not fetched, not admitted (`msi.nga.mil`, `www.navcen.uscg.gov` both fail `allows`), no content evidence. Commercial mirrors of the CFR (Cornell, lexfed, etc.) were left out as non-official.

## 3. Conclusions for G (no approval claimed)

1. The held source fails because the official host answers the pipeline's plain GET with an Akamai 403 "Access Denied". The cause on the server side is unknown from one observation.
2. No admitted official page carries both `Danger Zone 4` and `Vessel Safety Areas`. #1 carries only the first phrase and is a static rule, not the live launch-closure notice the held page provides. Using it would mean changing the keywords the watch requires, which is G's decision.
3. The live notice pages (#4, NGA, LNM) are on hosts the pipeline does not admit. Adding any would change the allowed-host input, which this report does not do.
4. Options for G: keep the hold (no change); sign a static-law replacement (#1) with a one-phrase keyword set; or ask for host admission plus a fetch check for a USCG/NGA notice page, which needs its own reviewed change and a successful fetch first.

No file other than this report changed. Observation scripts and raw bodies are kept outside the repo.
