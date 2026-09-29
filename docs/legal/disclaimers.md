# Disclaimers: the four legally necessary caveats

**Status:** Draft — pending review by counsel (2026-09-28). Not legal advice.

This file is the single source for the caveats SkipperCast must show for legal reasons. Every other limitation (survey age, datum, model spread, stale feeds) is *product honesty*, not a legal caveat: it belongs in confidence badges that link to the data-confidence page, not in repeated paragraphs (guide §5.8, §10.6).

Where these appear (guide §10.6):

1. the [terms of use](../../dist/terms.html) (full text, sections 2–5 and 9–10);
2. one first-launch acknowledgement (short form of all four; not yet built);
3. one persistent footer line: **“Planning aid · not a navigation chart”** (not yet built);
4. the Export sheet, before a chartplotter file is downloaded (C1 and C4 short forms).

When copy changes here, update the terms page and the in-app strings in the same PR. Do not weaken the *information* in a caveat when shortening it; only its presentation may change.

| Id | Caveat | Short form (UI) | Full form (terms) |
| --- | --- | --- | --- |
| C1 | **Not a navigation aid.** | Planning aid · not a navigation chart. | SkipperCast is a trip-planning aid, not a navigation aid or nautical chart. Do not use it for navigation, collision avoidance, anchoring, or to judge a harbor entrance, bar or passage. Maps, depths, outlines, bearings and exported waypoints can be incomplete, offset or wrong; use current official charts, your instruments and your own observation. |
| C2 | **Forecasts and model output carry no guarantee.** | Forecasts are estimates; conditions can differ. Check the NWS marine forecast. | Forecasts, comfort scores, habitat grades, search plans and alerts are estimates from models and automated processing of third-party data. They can be late, missing, stale or wrong, and actual conditions can differ sharply. A good score or alert is not a promise of safe conditions or of fish. Check the official NWS marine forecast and current observations before and during every trip. |
| C3 | **Verify regulations with the authorities.** | Rules change. Verify with CDFW and NOAA before you fish. | Regulations, seasons, limits, depth rules, protected areas and closures change, sometimes with little notice. SkipperCast summarizes and links official sources but is not legal advice or an official source. Verify current rules with CDFW and, for federal waters and groundfish areas, NOAA Fisheries. You are responsible for complying with the law. |
| C4 | **You assume the risks of the sea; no warranty.** | You are responsible for your boat, crew and decisions at sea. | Boating and fishing are dangerous. You alone decide whether, when and where to go and are responsible for your vessel, crew and passengers. SkipperCast is provided “as is”, without warranty, and its liability is limited as set out in the terms. |

Open questions for counsel: whether C4’s limitation of liability must also appear at purchase; whether the first-launch acknowledgement must be recorded server-side (`accepted_terms_version`) once accounts exist; arbitration and venue.
