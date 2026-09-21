# Local species regulations

Selecting a species opens a compact map card with today's Pacific-time season
status, dates, daily/possession limits, minimum size, gear details and official
CDFW links. It covers recreational boat fishing between Avila and Cambria and
adjacent offshore U.S. waters north of Point Conception. California halibut and
Pacific bluefin are explicitly distinguished from other fisheries. It is an
area-wide summary, not clearance for the selected GPS position: MPAs and the
Diablo Canyon security zone still apply. The weather timeline does not change
the card's clearly labeled **Today** date.

The reviewed rules are in [the registry](../dist/data/regulations.json), researched
September 21, 2026 from the official sources linked in every profile. The review
covers the remainder of 2026. It expires at Pacific midnight after December 31;
the app does not extrapolate these rules into 2027. The November 7 crab opener
is scheduled, not confirmation that traps will be allowed. That opening needs
a new review before the card can display open.

## Daily checks and publication

The existing `Daily fishing evidence` GitHub Actions workflow runs at 04:17
America/Los_Angeles, independently of the desktop. It fetches the regional rules,
groundfish, salmon, crab, gear, health, whale restrictions, local MPA pages,
in-season notices, official regulation index and the 2026 booklet. The PDF is
checked as a bounded PDF download; HTML is normalized to text before hashing.
The resulting rules packet is published atomically with `data/latest.json`.
The app loads that public feed, with a bundled dated fallback, and refreshes it
hourly while in use. Daily schedule delays remain visible through timestamps.

Every official source has a **reviewed content fingerprint**. A fresh successful
fetch must match that baseline. Changes remain flagged across daily runs until
reviewed; comparing only against yesterday would wrongly clear an unreviewed
change the next day. Missing, failed, retained, future-dated or >36-hour-old
checks withhold the green season-open badge for affected species. A successful
HTTP response alone cannot establish permission to fish. Whole-page changes can
cause conservative false alarms, which is preferable to silently accepting new
rules. Linked documents changing independently are not exhaustively monitored;
the user should still follow the official links before departure.

The workflow summary lists sources requiring review and emits an Actions warning.
This is a source-change monitor, **not automatic legal interpretation**. It does
not automatically change bag limits or send personal Telegram messages.

## Reviewing an update

1. Read the changed official source, its linked current regulations and relevant
   in-season notices. Distinguish recreational from commercial rules and verify
   geography, dates and gear. Review HTML/PDF changes even if limits appear unchanged.
2. Edit the affected profiles, season windows and review validity in the registry.
   Set `reviewed_at` to the actual review time and increment its revision.
3. Copy the reviewed source's `content_sha256` from a successful daily source
   record into `approved_content_sha256`. Never automatically approve a new hash.
4. Run the regulation tests and push the registry. This triggers another collection;
   the updated packet reaches the existing app without a website redeploy. For a
   website release also bundle its checked packet so the fallback is current.

Python tests cover persistent changes and failure handling. Browser module tests
cover species limits, Pacific date transitions, closed seasons, unconfirmed crab
opening, year expiry, stale checks, dependency isolation and safe links. Mobile
interaction is checked in the local preview before publication.
