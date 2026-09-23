# Recent local fishing discussion pipeline

The daily public-data workflow now runs a pinned [last30days](https://github.com/mvanhorn/last30days-skill) engine against region-specific searches. It saves a separate `recent-intel.json` candidate feed on the `data` branch. This adds discoverable, dated public discussions to the existing charter trip counts and government observations.

`catalog/recent-intel-watchlist.json` defines the regions, queries, source set, window, known regional fishing subreddits, and exact upstream commit. `scripts/collect_recent_intel.py` requests last30days' versioned agent JSON, records per-source outcomes, and keeps only HTTPS links with publication dates inside the window and a fishing term plus either an explicit local place or a regional fishing subreddit. A subreddit supports region-scale discovery only; no catch position is inferred. It strips tracking parameters and deduplicates by canonical URL. The upstream relevance score was zero on the first unrelated search and is not treated as fishing evidence. A failed source is reported separately from an empty result. Previously seen links may be retained with their original date and an explicit `retained` flag; a new run never gives them a fresh fishing date.

The first keyless Morro Bay test on September 22 returned seven unrelated Reddit items and zero keyless web results. The local place and fishing-term filter rejected all seven. Keyless coverage is useful for finding leads, but it cannot guarantee local reports on every run. Other sources require their own configuration or credentials. The scheduled job uses only `reddit,grounding` with keyless web search and browser-cookie access disabled; no third-party API keys or private data are supplied.

The feed does not claim any catch. Every candidate has `reported_catch:null`, `species:[]`, `fishing_date:null`, `geometry:null`, and `review_status:"candidate"`. Publication time, search query, URL, and source are preserved. A person reviewing one must read the original report, identify when and where the trip occurred, and record its precision and independent evidence before promoting it into the existing regional pipeline. Posts about a landing cannot become precise map points. Search engagement must not alter habitat grades, legal status, weather comfort, or catch likelihood.

A focused Southern California test found a [September 2026 white seabass self-report](https://www.reddit.com/r/SoCalFishing/comments/1wmqtwm/white_seabass_caught_yesterday/). In comments, the author named Horseshoe Kelp and described a 67-pound fish. The thread does not supply a verified GPS position, method, trip effort, or independent confirmation. It is a useful review lead, not a new hotspot or catch-rate input.

The current workflow runs once daily at 4:17 a.m. Pacific, alongside the existing data refresh. It rotates **one query per day** across five regional searches to reduce rate limits; all five are due once every five days. GitHub schedules can be delayed. The research engine is pinned to commit `349ca444b4fda466e74d471dffa2aff36bb997f1`; a version change requires a contract and output review. The workflow publishes a candidate snapshot even when a search degrades, then reports counts and source health. If its external checkout or the collector cannot run, the previous feed retains its original timestamp and the workflow exposes a failure. Candidate discovery has no effect on the app's current species ratings until individual observations pass review.

Run locally using Python 3.12 or later:

```bash
python scripts/collect_recent_intel.py --engine var/last30days-upstream/skills/last30days/scripts/last30days.py --output var/recent-intel
python -m unittest discover -s tests -p 'test_recent_intel.py' -v
```

For another coast, add a watchlist region and region-specific place terms, run representative searches, inspect the source health and false positives, and then extend the reviewed observation adapter. The data contract remains the same while local sources and search terms change.
