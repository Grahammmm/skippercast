# The conditions model

`web/score.ts` is the one conditions model. Every surface that rates the water
reads it; none keeps its own copy of the numbers.

| Surface | Reads |
| --- | --- |
| Tomorrow card, meteogram, search plans, trip planner (`dist/tomorrow.js`, `dist/morning-outlook.js`) | `hourScores`, `limitedScores`, `verdictFor`, `THRESHOLDS` |
| Text advisor comfort word (`server/advisor/answers/comfort.ts`, `conditions.ts`) | `rateComfort` (the comfort half of `hourScores` and `limitedScores`), `verdictFor` |
| Brief day verdict (`web/brief/verdict.ts`) | `rateComfort`, `comfortCosts` (to name the limit), `verdictFor`, `THRESHOLDS.capHazard` |
| Brief lower-exposure windows (`packages/coast/src/assessment.ts`, `daily.ts`) | `withinWindowLimits`, `WINDOW_LIMITS`, `LONG_PERIOD_SWELL` |
| Your limits (`packages/coast/src/limits.ts`, `web/limits.ts`) | `WINDOW_LIMITS` as the defaults |
| Boat brief fishing time and return (`web/brief/run.ts`) | the brief's lower-exposure windows, so the turn-back time inherits every rule above; no score of its own |

Every number is a disclosed planning heuristic tuned on the reference 23 ft
boat. None is a sea-keeping calculation, a safety clearance or a catch
probability.

## Two questions, answered on purpose by two rules

**The score** grades an hour from 0 to 10 for comfort and, when fishing the
bottom or the water column, for boat control. It charges wind, gusts, combined
seas and wind chop on slopes, adds flat penalties for a crossing secondary
swell and short steep chop, and caps any estimate built from partial fields.
`verdictFor` turns it into go, marginal or no-go.

**The window rule** asks whether an hour sits inside the person's own
numerical limits for wind, gusts and seas. The defaults are `WINDOW_LIMITS`
(boat 10 kt, 15 kt gusts, 4 ft; shore, spear and kayak 8 kt, 12 kt, 3 ft), and
the person can set them looser or stricter on the device. Seas of at least
2.5 ft at 15 s or longer keep an hour out whatever the limits, unless a fresh
nearshore model judges the hour (spear surge). An unknown field never fits a
window.

The two are kept separate because they answer different questions. A window
must stay in the person's own numbers, which the graded score cannot express,
and the long-period rule is a hazard screen for surge and the harbour bar, not
a comfort cost. Merging them would change what users see, so the decision is to
share one module and record where they part.

## Where they disagree

For the reference boat, `tests/test_score.mjs` compares the boat-comfort "go"
verdict with the default boat window on the 69 golden hours that carry a wave
period. They agree on 65:

- Three hours rate go but fall outside the window: two carry long-period swell
  (2.6 ft at 16 s and 3.4 ft at 15 s), and one has 12.8 kt wind, over the 10 kt
  default limit, that the graded score absorbs.
- One hour fits the window but rates marginal (6.9): short steep chop (0.6 ft
  at 3.5 s) costs its flat penalty, which the window rule does not see.

Change a threshold or a default limit and that test fails with the new list;
update this page in the same pull request.

## The day verdict

The brief's first line (`web/brief/verdict.ts`, #616) turns the score into one
word for the morning window: the whole hours starting at or after sunrise and
before noon on the brief's date (from the current hour when that is today;
once noon has passed, the hours starting before sunset). It is a comfort rating for the reference boat, not a bite or catch
forecast and not a safety clearance.

- **Boat.** Each hour is rated by `rateComfort` over the regional dual-model
  feed (NOAA GFS and GFS-Wave, ECMWF IFS and WAM) at the forecast point the
  Conditions view reads, the same function the text advisor uses. The worst
  hour sets the day through `verdictFor`: 7 and above is Comfortable, under 4
  is Rough, Marginal between. The sentence names the largest charge in that
  hour from `comfortCosts` (wind with its gust, combined seas with period, wind
  chop, or a crossing swell) and a second charge when it costs a point or more.
- **Shore, Spear and Kayak.** Their own hourly grades (`shore-conditions.ts`,
  `spear.ts`, `kayak.ts` in `packages/coast`), the roughest hour in the same
  window; Calmer reads Comfortable. The sentence leads with the hour's decisive
  or worst-band reasons (launch surf, fog, daylight, offshore wind before the
  wind and seas bands).
- **Never reassuring on thin evidence.** An active marine alert makes the day
  Rough. A Comfortable window is held at Marginal, with a sentence saying why,
  when any hour is a limited estimate, hours have no forecast, a model run is
  over 18 h old, the marine alert check is unavailable, or the bar estimate
  reads hazardous in the window. On a Marginal or Rough day a missing alert
  check is still said ("No current marine alert check."), and under an alert
  no hour score is shown. Runs over 36 h old are not used; with no
  forecast the verdict is Unknown. Buoy readings never enter it, so a stale
  buoy cannot raise it.

`tests/test_brief_verdict.mjs` pins the bands, the caps, the limit sentence
and the Unknown cases.

## Staleness and failover inputs

The feeds keep `ok`, `stale`,
`missing`, `failed` and `retained` distinct, and retained data keeps its
original retrieval time. When no station in a configured chain is fresh, the
collector serves the newest data by its own clock, so an older retained reading
never replaces a newer stale one
([station priorities](operations/station-failover.md)).

Saved-trip alerts (`server/alert-policy.ts`) still compare a trip's window
maxima (wind, gusts, seas and chop) with the limits saved on the trip. It reads
no wave period, so it has no long-period rule. That screen is unchanged here.
