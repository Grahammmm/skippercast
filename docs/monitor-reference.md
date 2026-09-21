# Forecast collector and alert lifecycle

The monitor code preserves public forecast evidence for a person to review. It
does not calculate a fishing or comfort score, decide a trip is safe, run a
schedule, store delivery state, or send a notification. The current source
profile covers **Morro Bay, California, with forecast samples from Cambria to the
Buchon approach**. The public atlas covers the smaller **Avila / Point
Buchon–Point Estero** survey subset; Cambria data is excluded pending reuse
permission clarity. See the [atlas guide](../atlas/avila-point-estero-2026-09-20/README.md).

## Collect a run

Use Python 3.11 or newer from the repository root:

```bash
python -m pip install -e .
skippercast collect --config configs/morro-bay.example.json --output var/runs/example
```

The module entry point is equivalent:

```bash
python -m skippercast.monitor.collector --config configs/morro-bay.example.json --output var/runs/example
```

Choose a **new** output directory each time. The collector refuses to overwrite
an existing directory. It makes read-only HTTP requests to public providers;
internet access and normal TLS certificate validation are required. It uses only
Python's standard library. When available, `curl` is resolved from `PATH` for
CDFW pages; without curl it tries Python's verified HTTPS transport. An IANA
timezone database must be installed on the system. On systems without one,
install the Python `tzdata` package separately.

The example config contains public locations and optional planning assumptions,
including a 20-knot cruise and a 200-foot fishing limit. Those planning values
are **metadata only**: this collector does not calculate travel time, a fishing
window, or a depth limit. It rejects unknown config keys, including accidental
credential fields. Weather sampling points are not fishing waypoints.

Changing the coordinates does not adapt the fixed NWS zone, buoys, legal sources,
or harbor references to another region. Only the `morro-bay` source profile and
its Pacific timezone are supported. General regional profiles require new source
adapters and local validation.

## What gets written

| File | Purpose |
| --- | --- |
| `NAME.raw.txt` | Exact response bytes, despite the text extension. |
| `NAME.meta.json` | Requested URL, retrieval/completion times, HTTP metadata, byte hash, and transport errors. |
| `NAME.text.txt` | Readable extraction when the response is HTML. |
| `manifest.json` | One access record for each attempted source. |
| `screen.json` | Requested locations, returned grid metadata, model timing, numerical ranges, and evidence gaps. |
| `result.json` | Collection status, access failures, and gaps. The same report is printed to stdout. |

Exit `0` means the implemented collection checks passed, **not** that a trip
qualifies. Exit `1` means source access or evidence is incomplete; examine the
saved run. Exit `2` means invalid configuration or an output-directory error.
Some requested variables are not published by every model, so real runs may
legitimately exit `1`. This makes missing evidence visible rather than treating
an absent swell partition or visibility field as zero.

The screen covers 06:00–13:00 Pacific for the **next seven future calendar
dates**, excluding today. Each range carries a count of populated hours. It is
an initial screen, not a complete departure-to-return assessment. A route may
require earlier departure, later return, or different exposure. No missing hours
are interpolated. All requested hourly variables remain visible when absent; malformed,
truncated, duplicate-time, and nonnumeric inputs create gaps. Wave heights in
meters are converted to feet only when their unit is explicit. Gusts below
sustained wind are retained and flagged for investigation.

## Sources and limits

The collector requests ECMWF IFS and NOAA GFS winds, plus ECMWF WAM and NOAA
GFS Wave seas, through [Open-Meteo](https://open-meteo.com/en/docs). Open-Meteo is
the access service, not another independent forecast model. Model metadata comes
from the provider's [model-update endpoints](https://open-meteo.com/en/docs/model-updates).
Initialization, availability, and published coverage are recorded separately.
Retrieval time, HTTP Date, and `generationtime_ms` are not model issue times.
Latest-run metadata does not establish which run produced every seamless value;
populated values beyond its coverage are flagged for further attribution.

Returned coordinates in a combined-model response do not establish every
model's native grid. Nearby samples can share a coarse sea cell. Single-model
requests and local observations are needed before claiming differences in
shelter, the entrance, or drift. The collector does not automatically wait for
provider replication or compare forecasts against observations.

Other responses saved for human review include:

- [NWS PZZ645](https://forecast.weather.gov/MapClick.php?TextType=2&zoneid=PZZ645),
  the [Los Angeles/Oxnard discussion](https://forecast.weather.gov/product.php?issuedby=LOX&product=AFD&site=lox),
  and [active zone alerts](https://api.weather.gov/alerts/active/zone/PZZ645).
- [NDBC 46215](https://www.ndbc.noaa.gov/station_page.php?station=46215), its
  wave partitions, and [NDBC 46028](https://www.ndbc.noaa.gov/station_page.php?station=46028).
  Inspect observation timestamps and missing-value codes; the code does not
  interpret them as current verification.
- [Port San Luis 9412110 tide predictions](https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id=9412110).
  These are a nearby reference, not Morro Bay entrance tides or currents.
  High/low water does not establish slack current; bottom currents are unknown.
- [Morro Bay harbor information](https://www.morrobayca.gov/156/Weather-Boating-Information)
  and the [Harbor Department](https://www.morrobayca.gov/144/Harbor).
  General webpages are not live entrance clearance.
- [CDFW groundfish rules](https://wildlife.ca.gov/Fishing/Ocean/Regulations/Groundfish-Summary),
  [in-season changes](https://wildlife.ca.gov/Fishing/Ocean/Regulations/Inseason),
  [Point Buchon MPAs](https://wildlife.ca.gov/Conservation/Marine/MPAs/Point-Buchon),
  and [Cambria/White Rock MPAs](https://wildlife.ca.gov/Conservation/Marine/MPAs/Cambria-White-Rock).
  Saving a page does not interpret or establish current compliance. The Diablo
  Canyon security restriction and any applicable Coast Guard notices require
  separate current review; those sources are not automatically collected.
- [Virg's fish counts](https://www.virgslanding.com/fish-counts.php), whose dates,
  area, depth, and trip type must be inspected before use. Historical catches do
  not predict catch success.

An HTTP 200 response can still be stale or incomplete. Published issue times,
validity periods, legal changes, advisories, entrance conditions, swell
directions, visibility, effective bottom contact, and route timing remain human
review responsibilities. No webpage is executed as an instruction.

## Alert lifecycle helper

`skippercast.monitor.lifecycle` is a separate pure module. A caller supplies a
reviewed assessment and the state of **successfully delivered** messages. It
returns one action name or `None`; it never delivers an alert or changes state.

`qualifies()` requires both externally assigned scores to be 9–10, confidence
`Moderate` or `High`, explicit verification and numerical-target flags, and
explicitly empty hazard and critical-gap lists. Missing or null lists fail the
gate. The function cannot establish that those assertions are true. It must not
be used to convert numerical thresholds into automatic safety scores.

`action_for(trip_date, assessment, previous, now)` requires a timezone-aware
`now` in the planning timezone. Initial qualification returns `Early opportunity`;
loss of qualification returns `No longer qualifies`; changed material fields
return `Update`. A previously alerted date stays active after retraction. At or
after 18:00 on its previous date, it requires a `Day-before assessment` even when
unchanged or retracted. First qualification that evening also uses the final
assessment. A final stops monitoring only after successful delivery is recorded.
Past dates with an undelivered final return `Missed final assessment` once after
the caller records `missed_final_reported`.

Integrations must reconcile ambiguous sends, preserve stable event IDs, and
record successful receipts before changing delivered state. Delivery,
scheduling, credentials, and the original private integration are intentionally
outside this repository.

## Offline verification

```bash
python -m unittest discover -s tests -p 'test_monitor.py' -v
```

The fixtures exercise missing variables, truncated arrays, invalid numbers,
duplicate times, gust conflicts, units, model coverage, local-date selection,
nonzero incomplete runs, retractions, final assessments, and missed finals.
Tests never fetch live forecasts or send messages.
