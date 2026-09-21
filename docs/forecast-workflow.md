# From forecast evidence to an assessment

This workflow describes operator or agent review around the shipped collector and alert rules. It is not a fully automated forecast or delivery service.

## 1. Choose a real trip window

The example profile plans for a 23-foot boat cruising at 20 knots in suitable conditions, at least four actual fishing hours, 15 minutes of harbor travel each way, a 12:30 return target, and a 13:00 deadline. Reduce the speed when conditions require it. Searching, transit, and harbor travel do not count as fishing time.

Evaluate north and south separately. Use charted outbound and return routes; do not infer travel from an unchecked straight line. Review daylight and the entrance at departure and return. Inspect every part of the trip through the return margin, including afternoon wind increases and how wave direction meets the boat's heading.

## 2. Collect and examine the sources

Run the [collector](quickstart.md#collect-live-evidence), then inspect its raw responses, manifest, model metadata, and screen. Check fresh NWS PZZ645, the LOX discussion, applicable advisories, buoy observations, local notices, rules, and the other [source records](data-sources.md). Recover a transport failure with another fresh official read where possible; record both the failed access and recovery.

Compare **ECMWF IFS versus NOAA GFS** for wind and **ECMWF WAM versus NOAA GFS Wave** for seas at matching hours and relevant grid cells. Open-Meteo provides access to these models; it is not another independent model. Its combined response grid is not proof of each underlying model's grid. Check single-model results where matching locations matters.

Record actual model initialization, availability, populated coverage, forecast issue times, and returned coordinates. HTTP retrieval time and `generationtime_ms` are not issue times. Latest-run metadata does not prove every returned forecast value belongs to that run. Respect replication delays and never extend a source beyond its populated forecasts.

Missing values stay missing. Investigate gusts below sustained wind or inconsistent wave components. Review combined significant seas, primary and secondary swell height/period/direction, wind chop, visibility, precipitation, currents where available, and tides. Compare current buoy observations with matching forecast hours; current observations cannot validate next week's forecast. NDBC and CDIP reports of the same buoy are one observation.

Port San Luis tides are a **nearby reference**, not a Morro Bay entrance-current prediction. High or low water does not establish slack current. Do not invent bottom-current speeds. A general harbor information page does not establish live entrance clearance.

## 3. Check whether the fishing plan is legal and practical

Freshly review CDFW seasons, depth and gear rules, in-season changes, protected areas, and the Diablo Canyon security restriction before recommending an area. Check the entire proposed drift, not just a point. The example's 200-foot fishing ceiling is separate from whatever legal depth rules apply on the actual date.

The atlas is dated habitat research. Use only points that fit the current plan's region and restrictions. Maintainable bottom contact and a manageable drift matter to the fishing-condition score; no score predicts a catch. Recent, dated local catches can add context, but old reports, charter schedules, and solunar ratings cannot establish current success or override conditions.

## 4. Record a defensible assessment

Apply the [fixed rubric](assessment-rubric.md). Record both scores and their reasons, separate confidence, area, departure/fishing/return times, hazards, unresolved critical gaps, `verification_complete`, and `meets_numeric_targets`. Use null/unrated when evidence cannot support a score. Dates four through seven days away remain provisional.

The lifecycle module checks supplied flags and scores; it cannot establish that the input assessment is truthful or complete. The caller must verify that at least four fishing hours and all numeric/trip requirements actually hold before setting those flags.

## 5. Decide whether to notify

Use `action_for(trip_date, assessment, previous, now)` from `skippercast.monitor.lifecycle` with a timezone-aware local time and **delivered** prior state:

1. Send an initial alert when a future date first qualifies.
2. Send material changes and explicit retractions when it falls below the threshold or evidence can no longer verify it.
3. Continue monitoring every previously alerted date, including retracted dates, through its previous evening.
4. At or after 18:00 the day before, provide a final assessment even if unchanged or retracted. First qualification that evening can use one combined initial/final message.
5. Stop routine monitoring only after confirmed final delivery. Report a missed final once, without backdating it.

Unchanged assessments and dates that never qualified remain quiet. Access, scheduling, and delivery failures need a distinct failure report; they are not ordinary “no opportunity” outcomes.

## 6. Deliver through your own integration

No sending adapter is shipped. A production adapter must use a stable event ID, prevent duplicate sends, and update delivered state only after a successful receipt. Hold interrupted or ambiguous attempts for reconciliation rather than inventing a new ID to resend. Do not commit delivery records or credentials.

An assessment message should contain: type; date and area; overall and component scores; confidence and reason; departure/fishing/return times; wind; combined seas and available components/chop; tides/currents/entrance; changes or rationale; and direct sources with issue times. Use local time, knots, feet, and seconds for this profile. Every final assessment must say: **Recheck current marine and entrance conditions before departure.**

Scheduling, saved per-date state, receipt reconciliation, and failure deduplication remain integration work. Running the collector once does not start a monitor.
