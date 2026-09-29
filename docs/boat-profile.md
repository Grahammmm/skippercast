# Boat profile

SkipperCast's comfort and drift-control ratings were tuned on one boat: a 23 ft, roughly 4,500 lb loaded, 20° deep-V walkaround. The **Boat** button in the header lets you enter your own boat. The ratings then scale to its size and hull.

## Using it

1. Tap **Boat**, type the make, model and year, and choose **Look up with AI** (requires sign-in), or enter the numbers by hand.
2. Check every field. Numbers from the lookup carry an **AI estimate** tag until you edit them, and the builder sources it used are linked.
3. **Save boat.** The profile stays in this browser. The header then shows the boat's length, and every hourly and daily rating uses it. **Use reference boat** clears it.

## AI lookup

`POST /api/boat/lookup` asks a Claude model (`claude-sonnet-5` by default, or `BOAT_AI_MODEL`) with web search to find the builder's specification sheet or a reputable boat test. The model returns JSON: length, beam, dry and loaded weight, deadrise, hull type, layout, cruise speed, horsepower, fuel, confidence, inferred fields, notes and sources.

The Worker applies the same range checks as manual entry (`normalizeBoat`) and discards implausible values. Lookups:
- need sign-in;
- are limited to 20 per person per day, and to `BOAT_LOOKUP_GLOBAL_DAILY_LIMIT` (default 500) across everyone per UTC day; either limit answers 429;
- are cached for 30 days per boat name;
- send only the typed boat name.

**Cost controls.** Setting `BOAT_LOOKUP_ENABLED` to `"false"` switches lookups off (503, manual entry still works); on Cloudflare these vars live in `wrangler.jsonc`, so a dashboard edit lasts only until the next deploy — commit the change too. Each lookup logs one JSON line, `{"event":"boat_lookup","outcome","model","turns","input_tokens","output_tokens","web_search_requests"}`, with no query or owner. When a Workers Analytics Engine dataset is bound as `ANALYTICS`, the same numbers are written as a data point (blobs: event, outcome, model; doubles: input tokens, output tokens, searches, turns).

**Setup:** add the `ANTHROPIC_API_KEY` GitHub Actions secret; the Cloudflare deploy uploads it as a Worker secret ([Cloudflare](cloudflare.md)). Without it, the lookup answers 503 and the sheet asks for manual entry. Web search costs $10 per 1,000 searches plus tokens; each lookup uses up to 4 searches.

## Handling model (`dist/boat-handling.js`)

A saved boat produces two multipliers relative to the reference boat, plus a chop period:

- **Seas (`sea`)** = (length / 23 ft)^0.9, adjusted by:
  - weight for length: (weight / reference weight scaled by length³)^0.15, within ±15%;
  - hull: deep-V 1.0, modified-V 0.88–0.98, flat 0.75–0.87, power catamaran 1.08;
  - layout: pilothouse 1.05, walkaround 1.0, dual console 0.98, center console 0.97, skiff 0.9.

  The result is normalized so the reference boat is exactly 1, and bounded to 0.45–2.6.
- **Wind (`wind`)** = (weight / 4,500 lb)^0.2 × (length / 23 ft)^0.3, a proxy for drift control (windage against mass), bounded to 0.6–1.8.
- **Short-chop period** = 6 s × √(length / 23 ft).

The seas multiplier scales every wave-height threshold (combined seas 1.5 ft, chop 0.4 ft, secondary swell 1 ft) and divides the penalty per foot. The wind multiplier does the same for wind (4 kn) and gusts (7–8 kn). With no saved boat, or the reference boat, ratings are unchanged.

## Limits

This is a disclosed heuristic based on planing-hull rules of thumb. It is not a sea-keeping model, and it does not rate seaworthiness, stability or safety. It ignores:
- heading relative to the seas;
- loading and trim;
- skipper experience.

The in-app comfort feedback (`/api/comfort`) is the path to calibrating it against real trips. AI lookups can match the wrong variant or model year; the saved numbers are whatever you confirm.
