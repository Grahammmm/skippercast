# Open questions for the owner

Each section is one decision only the owner can make: money, terms of a
third party, credentials, or what the public sees. Options are ranked, best
first, and the pick is marked **(recommended)**. Until the owner answers, the
build follows the "Plan assumes" line and keeps going; the owner overrides by
saying so, and the change lands as a PR that edits this file and the affected
dev-plan tasks. Costs and facts come from the research spikes of 2026-10-04
(see [design.md](design.md) § 1. Overview and goals, research findings).
Task ids (CF-xx) and phases (P0–P6) refer to [dev-plan.md](dev-plan.md).

## Q1. aisstream.io terms for real-time AIS

**Context.** aisstream.io is free and supports a bounding box plus up to 200
MMSIs per subscription, but it publishes no terms or licence: `/terms` is a
404 and GitHub issues asking about commercial use and display (aisstream/aisstream
issues #16, #289, #290, #299, #303) are unanswered. The paid alternative with published
pricing is Datalastic (Experimenter €569/month, about $620; Developer Pro+
€679/month, about $740), whose redistribution terms are also unpublished.

1. **Use aisstream internally now and ask for written terms (recommended).**
   Collection for admin views and research carries no display exposure, and
   the adapter interface lets Datalastic replace it later.
2. Wait for written terms before collecting anything. Loses every day of
   tracks until an answer that may never come.
3. Pay Datalastic now (~$620/month). Buys a vendor relationship but not
   clearly better terms, and hourly polling is coarser than the stream.

**Owner action for option 1:** open an issue or email at
<https://aisstream.io> asking for written permission to store positions and
show derived maps on skippercast.com.
**Plan assumes:** option 1; no public per-vessel display (see Q8).
**Blocks:** nothing in the build (CF-40 builds the aisstream adapter). Blocks
any public AIS-derived layer.

## Q2. NOAA MarineCadastre usage conditions

**Context.** MarineCadastre daily CSVs are free and cover January–June 2026
today. NOAA's June 2026 FAQ adds the USCG NAIS conditions: use is "intended
for coastal and ocean planning purposes only" and redistributors "shall not
charge a fee for its usage". The repo currently labels the source CC0, which
understates those conditions.

1. **Use it for internal backfill and verification, tag every derived row by
   source, and exclude it from any paid surface (recommended).** Matches the
   stated conditions and costs nothing.
2. Don't use it. Loses the only free 2026 history.
3. Replace it with paid history (see Q6).

**Plan assumes:** option 1 (decision D9); CF-06 records the conditions in
`docs/legal/data-rights-register.md` and CF-47 tags derived rows
`noaa-planning-only`; CF-06 also corrects the CC0 label in
`docs/data-sources.md`. Backfill retention (CF-47 default, owner may override):
the backfill keeps positions and statics of target vessels only, and expires
them like the live store (`thresholds.retention`: positions `raw_days`, statics
`static_days`), counted from ingest because NOAA's days are already months old;
derived trips, events and aggregates stay.
**Blocks:** nothing.

## Q3. TECK.net report sites for a paid product

**Context.** SoCalFishReports, SanDiegoFishReports, NorCalFishReports and
SportfishingReport.com (all TECK.net) allow all crawling in robots.txt and
have no terms page, only "All Rights Reserved". They were the best seed list
in the pilot (148 provenance-tagged values for 21 boats) and the repo already
reads dock totals from them.

1. **Use facts only (names, specs, landings, counts) now; the owner writes to
   TECK.net before any paid or sponsored surface uses them (recommended).**
   Facts are low risk; a partner relationship is worth more than silence.
2. Ask TECK.net now, before using them in the registry. Delays the seed list
   for no added safety on facts.
3. Avoid them. Loses about 270 boats of seed data.

**Owner action:** email the publisher via the contact link on
<https://www.socalfishreports.com>.
**Plan assumes:** option 1 (CF-13 stores facts only).
**Blocks:** nothing in MVP. Blocks sponsorship or ads that rely on report-site
data.

## Q4. Send the CPRA request to CDFW

**Context.** CDFW issued 563 CPFV licences in 2025. Fish and Game Code
§ 8022(b)(2) makes vessel names, registration numbers, licence numbers and
licensee names public on request. No public list exists. The request costs
nothing beyond any duplication fee (capped at $50 in the draft) and takes 10
days for a determination. Item 2 (guide licences) closes the Delta gap.

1. **Send it as drafted, both items, now (recommended).** It is the only
   definitive list of six-packs, which no other lawful source covers.
2. Send item 1 only. Simpler, but leaves the Delta guides unknown.
3. Don't send. Coverage of independent six-packs stays near the 70% the
   aggregators give.

**Owner action:** paste the appendix text at
<https://wildlife.ca.gov/General-Counsel/Public-Records-Requests> ("Submit a
PRA Request"), electronic delivery.
**Plan assumes:** option 1; the CDFW list adapter is built against a
synthetic CSV and run when the records arrive.
**Blocks:** the CPRA-list ingest run in CF-62 (the file-import adapter in
CF-16 is not blocked). Repeat yearly after 1 April.

## Q5. Google Places API key

**Context.** Places is the lawful route to operator websites and aggregate
ratings. Text Search Pro is $32 per 1,000 after 5,000 free a month; Details
has 10,000/5,000/1,000 free a month by tier. A statewide sweep of about 420
boats and 30 ports fits the free tier. Only `place_id` may be stored long
term; rating and count follow the API's caching rules.

1. **Create a key restricted to the Places API with a daily quota cap and a
   $1 budget alert (recommended).** Free in practice, and the cap makes a
   bill impossible.
2. Skip Places. Ratings stay at 0% filled and some independents stay unfound.

**Owner action:** create the key at
<https://console.cloud.google.com/apis/credentials> and add it as the
repository secret `GOOGLE_PLACES_API_KEY`.
**Plan assumes:** option 1; the Places adapter is built and tested offline
and no-ops without the key.
**Blocks:** the Places enrichment run in CF-62, not the code (CF-16).

## Q6. Paid backfill for July–October 2026

**Context.** Free MarineCadastre data for July–September is expected around
mid-December 2026 and October around March 2027. Datalastic history is 1
credit per vessel-day; about 60 matched boats × 120 days ≈ 7,200 credits fits
one month of Starter at €199 (about $215). Satellite history for Baja trips
(Spire or MarineTraffic) is quote-only, likely $1,000+.

1. **Wait for the free data in December (recommended).** The season's maps
   are for learning, not a deadline; $0.
2. Buy one month of Datalastic Starter (~$215) after testing it on two boats
   already seen in MarineCadastre. Gets this season's tracks now.
3. Request a satellite history quote. Only adds offshore Class A long-range
   trips.

**Plan assumes:** option 1. The processor accepts any source through the
same adapter, so option 2 needs no new code beyond the Datalastic adapter
(a stub in CF-40).
**Blocks:** nothing.

## Q7. Own AIS receiver

**Context.** About $250–400 once (dAISy or RTL-SDR, Raspberry Pi, antenna)
plus about $5/month. From Morro Bay it reaches about 11–20 nm (35 nm from a
ridge). It would earn a free AISHub key, but adds no coverage for Southern
California or offshore, and NAIS already hears Class B inside Morro Bay.

1. **Defer (recommended).** Little new coverage for the cost and effort.
2. Buy one now for Central Coast freshness and an AISHub key.

**Plan assumes:** option 1.
**Blocks:** nothing.

## Q8. Public exposure of per-vessel tracks

**Context.** The admin map shows every stop and route (decision D11). Public
display raises three problems: no licence from aisstream (Q1), operators'
business sensitivity about their spots, and identity errors (many same-name
pleasure boats in AIS).

1. **Admin only for now; decide after at least 7 days of ingestion and the
   classifier validation (recommended).** The data will show what is safe and
   useful to publish.
2. Publish aggregates only (≥ 1 km cells, ≥ 3 distinct vessels, ≥ 72 h delay),
   with the existing "not a catch or hotspot claim" copy.
3. Publish named tracks for operators who opt in (`named` consent, US-C4).

**Plan assumes:** option 1; the aggregate module (CF-44) and the
`fleet_vessels.map_display_consent` column (CF-02) exist so options 2 and 3
are configuration plus a UI task.
**Blocks:** US-A7 and any public map task (none is in the plan; CF-50 and
CF-51 are admin only).

## Q9. Registry data stays out of the public repo (confirm)

**Context.** The repo is public. Decision D13 keeps contacts, OSINT output,
positions and outreach notes in D1 and on Hermes, with synthetic fixtures and
`scripts/check_repository.py` extended to `tests/fixtures/fleet/` and this
folder (CF-05).

1. **Confirm the policy as decided (recommended).** Keeps the repo public and
   the data private with no new cost.
2. Make the repo private. The privacy rules would still be needed, and the
   project would lose the benefits of being public.

**Plan assumes:** option 1.
**Blocks:** nothing.

## Q10. Delta guides and inland waters

**Context.** The scope is salt and tidal water, which includes the Delta.
Many Delta guides run boats under 25 ft on a Sport Fishing Guide licence, not
a CPFV licence (FGC § 46), so they are absent from the CPFV list. The
estimate is 30–45 Delta operators, of which NorCalFishReports covers about
10. Inland lakes and rivers are reserved (`waters = inland`).

1. **Include Delta guides now as `waters = delta`, filled from report sites,
   Places and CPRA item 2; keep inland out (recommended).** They are in scope
   and the guide list will arrive with the CPRA reply.
2. Defer Delta guides until the guide-licence list arrives.
3. Add inland waters now. Widens scope with no source plan.

**Plan assumes:** option 1.
**Blocks:** nothing.

## Q11. Raw AIS retention on Hermes

**Context.** Raw positions stay on Hermes only (D3). Trips, segments, events
and aggregates are kept permanently in D1. Reprocessing after a threshold
change needs the raw data. A watch list of a few hundred boats is small next
to Hermes's disk, so storage is not the constraint; privacy is.

1. **30 days (recommended).** Enough to re-run a threshold change on recent
   data and to cover a missed processor run; keeps private data short-lived.
2. 90 days, for one season of re-runs.
3. 7 days, the minimum for health checks.

**Plan assumes:** option 1, set in `fleet.json` (CF-04) so it can change
without code; CF-40 enforces it.
**Blocks:** nothing.

## Q12. Fish City as a benchmark

**Context.** Fish City (fishcity.app) lists 204 California boats and allows
crawling, but its terms forbid republishing its data, and it competes with
SkipperCast.

1. **Use its per-port counts by hand as a completeness benchmark only
   (recommended).** No data is copied.
2. Ignore it.

**Plan assumes:** option 1; no adapter is written for it.
**Blocks:** nothing.

## Q13. Self-hosted fleet jobs on a public repository

**Context.** [docs/operations/runners.md](../../operations/runners.md) says
self-hosted runners must be used only while the repository is private,
because on a public repository anyone's pull request could run code on the
box. The repository is public, and the fleet workflows run on Hermes through
`DATA_RUNNER` (CF-18, CF-21, CF-42, CF-45, CF-47). The plan never triggers a
fleet workflow on `pull_request`: they run on schedule or `workflow_dispatch`
from `main` only, and CF-18 and CF-21 test that.

1. **Keep as planned (recommended).** No fork pull request can reach Hermes
   through a fleet workflow; runners.md gains a line stating the condition
   (no `pull_request` trigger on any `DATA_RUNNER` workflow) in CF-42, which
   already edits that file.
2. Make the repository private. Removes the exposure but, per the owner's
   earlier decision, loses free branch protection, which `main` relies on.
3. Run the fleet jobs on GitHub-hosted runners. Removes Hermes from the
   path, but the listener's raw AIS store, run directories and the Claude
   token live on Hermes, so the processor and OSINT jobs would need a new
   design, and the minutes become paid if the repository ever goes private.

**Plan assumes:** option 1.
**Blocks:** nothing; CF-18, CF-21, CF-42, CF-45 and CF-47 build on it.

## Q14. Commercial use and the deployment's data-use flags

**Context.** `deployments/production.json` declares
`"source_use": "noncommercial"` and `"monetization": "none"`. Tracked
`/go/` links to operators (CF-34), and later sponsorship, ads or booking,
would change that, and several sources carry conditions on paid use
(MarineCadastre in Q2, TECK.net in Q3, aisstream in Q1).

1. **Revisit before any paid surface ships (recommended).** `/go/` links
   with UTM tags earn nothing and stay within `noncommercial`; the flags,
   the data-rights register and Q1–Q3 are reviewed together when a paid
   feature is proposed.
2. Revisit now. Settles the flags early, but there is no paid feature yet to
   judge the terms against.

**Plan assumes:** option 1; no task changes the flags.
**Blocks:** any sponsorship, ad or booking task (none is in the plan).

## Q15. A removal request is permanent until cleared

**Context.** When an operator asks for a boat to be hidden or removed (US-C3),
`fleet_vessels.removal_requested_at` is set. Every public read (the profile,
`/go/`, the sitemap; `publicVesselSql` in `server/fleet/display.ts`) treats a
non-null value as unlisted, even if an admin later sets `profile_status` to
`listed`. Re-publishing therefore needs the timestamp cleared, which no task
builds yet.

1. **Keep it permanent until an admin clears it with a recorded reason
   (recommended).** The operator's wish wins over a stray "listed" click; CF-31
   shows the state ("removal requested on <date>: not public") beside the
   listing control and offers "clear removal request" as its own audited admin
   fact.
2. Let "listed" override the request. Simpler, but one click re-publishes a boat
   whose operator asked to be removed.

**Plan assumes:** option 1; CF-31 must show the state.
**Blocks:** CF-31's listing controls.

## Q16. MarineTraffic and VesselFinder pages for the OSINT agent

**Context.** The `charter-osint` agent first listed MarineTraffic and
VesselFinder vessel pages as sources for matching a boat to its MMSI. Their
terms were not re-checked for this use, and MarineTraffic's terms restrict
automated access. CF-21 moved both to the agent's "Not yet cleared" list,
and the headless runner denies WebFetch to `marinetraffic.com`,
`vesselfinder.com` and their subdomains (`NOT_CLEARED` in
`scripts/fleet/run_osint.py`). ITU MARS, USCG PSIX and the operators' own
pages remain the MMSI sources.

1. **Leave both out until their terms are reviewed (recommended).** Costs
   some MMSI matches; AIS matching (CF-46) can recover some of them from
   broadcast static names without either site.
2. Review the terms now and clear whichever allows occasional manual-rate
   lookups; the change moves the host back to "Sources you may fetch" and
   out of `NOT_CLEARED` in one PR.
3. Add both to `catalog/fleet/off-limits.json` (D7) as forbidden. Makes the
   exclusion permanent and also refuses profiles that cite them at ingest,
   before anyone has read the terms.

**Plan assumes:** option 1.
**Blocks:** nothing; MMSI coverage from the OSINT step is lower until decided.

## Packaging: two skills (owner, 2026-10-10)

**Resolved.** The charter-fleet run is packaged as two skills, `skippercast-fleet-registry` (#468) and `skippercast-fleet-activity` (#469), not one combined `skippercast-charter-fleet` skill. Reason: they run on separate schedules and fail independently; the only hand-off is the watch list, which the registry skill writes and the activity skill reads.

## Appendix: CPRA request text

Submit at <https://wildlife.ca.gov/General-Counsel/Public-Records-Requests>
("Submit a PRA Request", GovQA). Paste the text below into the description,
choose electronic delivery and fill the brackets.

> **Subject:** Public Records Act request: current Commercial Passenger
> Fishing Vessel (CPFV) licence list
>
> Under the California Public Records Act (Gov. Code § 7920.000 et seq.) and
> Article I, § 3 of the California Constitution, I request copies of the
> following records:
>
> 1. A list of all Commercial Passenger Fishing Vessel licences (FGC
>    §§ 7920–7925) issued for licence year 2025–26 and licence year 2026–27
>    to date. For each licence, I ask for these fields as they exist in the
>    Automated License Data System (ALDS) or any successor system: vessel
>    name; CDFW commercial boat registration number ("FG" number); CPFV
>    licence number and licence year; licensee name as issued (the business
>    name where the licensee is a business, or the name as permitted under
>    FGC § 8022(b)(2) for an individual); the vessel's USCG official
>    documentation number or California (CF) registration number, if
>    recorded; home port or port of operation, if recorded; and whether a
>    CPFV Crab Trap Validation was issued (2026–27).
> 2. Optional, separately severable: a list of current Sport Fishing Guide
>    licences (FGC § 2536) that record a guide boat or that operate in the
>    Sacramento–San Joaquin Delta or San Francisco Bay, with licence number,
>    licensee or business name, and county or water body of operation, if
>    recorded.
>
> **Legal basis.** FGC § 8022(b)(2) provides that "fish business
> identification numbers, fish business names, commercial fishing license
> numbers, commercial fisher names, vessel registration identification
> numbers, and vessel names, exclusively, shall be deemed public information
> and may be provided upon request." This request does not seek logbooks,
> landing receipts, catch or effort data, or any other records made
> confidential by FGC §§ 7923 or 8022(a).
>
> **Personal information.** I do not seek residential addresses, personal
> telephone numbers, email addresses, dates of birth, Social Security or
> driver's licence numbers, or payment information; please redact or omit
> them. If you withhold any field (for example home port), please release the
> remaining fields and identify the exemption relied on for each withheld
> field (Gov. Code §§ 7922.000, 7922.540).
>
> **Format.** Under Gov. Code § 7922.570 et seq., please provide the records
> in the electronic format in which they are held, or as a CSV or Excel
> export from ALDS. An existing report or extract is acceptable; I am not
> asking CDFW to create a new record.
>
> **Fees.** I agree to pay direct duplication costs up to $[50]. Please
> contact me before incurring more.
>
> Please tell me within 10 days whether the records are disclosable (Gov.
> Code § 7922.535). If part of the request is unclear or too broad, I am
> happy to narrow it: [business email / phone].
>
> Thank you,
> [Name], [Organization], [business mailing address]

**If CDFW pushes back:** home port and address are not among the
§ 8022(b)(2) fields and may be withheld. If CDFW cites § 8022(a) for the
whole list, reply quoting § 8022(b)(2) and accept the four public fields
only. Individual licensee names are used only to join records and are never
published or stored beyond the join; the registry stores the operating
business name.
