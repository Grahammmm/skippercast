# 00. Decisions, principles and boundaries

## What the Text Advisor is

A professional fishing advisor people text. One SkipperCast phone number.
Anyone texts it for a fishing report, a fish ID or rigging advice. Skippers
(charter and party-boat captains, landing staff, crew) text in count-board
photos, catch photos, counts and videos; those become fish reports on the
website and posts on SkipperCast's Instagram and Facebook Page, credited and
tagged to the boat. Social pulls people in, the advisor answers them, the
website carries the depth (maps, charts, boat pages). It is a loop:

```
skipper content ──► data platform ──► social posts + text answers ──► website
      ▲                                                                   │
      └──────────── more bookings for the skipper ◄───────────────────────┘
```

v1 has no bookings or payments. Central Coast first (Morro Bay, Port San Luis,
Avila), built so other regions are configuration.

## Decisions made by the owner (3 Oct 2026)

| # | Decision | Consequence for the build |
| --- | --- | --- |
| D1 | **Channel: self-hosted iMessage + SMS on a number SkipperCast owns.** A real SIM/eSIM in a spare iPhone, a dedicated Mac mini running the BlueBubbles server, both signed into one dedicated Apple Account. Twilio on the *same* number is the fallback if the relay breaks or Apple cuts it off; nobody is ever told a new number. WhatsApp is Next, not MVP. | The Worker never talks to iMessage directly. It talks to a **channel adapter interface** (`server/advisor/channels/`), with three implementations: `bluebubbles`, `twilio`, `web`. Switching is configuration (`ADVISOR_CHANNEL`), not code. The port-to-Twilio runbook is a deliverable, not an afterthought. |
| D2 | **Vision: the Hermes local classifier first, Claude vision as fallback.** Nothing in this repo does image reading today; the owner's Hermes machine (Ubuntu, Tailscale) will expose a classifier. Its exact interface is not yet known. | One **vision provider interface** (`server/advisor/vision/`) with two providers behind it. The Hermes provider is built against a contract this plan defines (`07-vision.md`); if Hermes cannot meet it, the owner decides whether to adapt Hermes or ship Claude-only. Claude vision is complete and tested on its own, so the feature never waits on Hermes. |
| D3 | **MVP scope stays as the doc marks it**, plus FC-6 (Spanish), WH-4 (port and species pages), OP-6 (rules table), OP-7 (channel fallback), OP-8 (vision providers). SP-2 (Facebook cross-post) is absorbed into SO-4. | The work breakdown covers the 50 MVP stories in the doc (the story-to-task map in 10 lists each); SC-5's auto-publish offer is built dark in the same task as reports because it is one code path, but stays off (Next). Social automation that needs Meta app review (SP-8, SP-9) is scheduled so engineering is done while review runs, and ships dark until approval. |
| D4 | **Admin lives on skippercast.com**, passkey-gated, under `/admin/*`. | New `server/routes/admin.ts` plus a small Preact admin app under `web/admin/`. Admin is a role column on `users`, granted by the owner through a one-off script, never self-serve. |
| D5 | **No social assets exist yet.** | Phase S0 in the breakdown creates them; Meta app review is on the critical path for SP-8/SP-9 only. |
| D6 | **`claude/email-sign-in` is superseded.** The advisor takes migrations `0006` onward and adds phone identity on the existing `users` table. | That branch is closed with a note in its PR-less commit; if email sign-in returns later it is rebuilt on `0010+`. |
| D7 | Open-question defaults the plan assumes until the owner says otherwise: confirm the first 5 reports then offer auto-publish (SC-5); the advisor calls itself "SkipperCast" in a friendly captain-like voice; skipper photos go to the review queue first, then Instagram with the boat tagged; first paid service is premium alerts and briefs (not built, but free answers link toward it). | Encoded in prompts and the `advisor_settings` defaults; all four are runtime settings. |

## Principles the code must honour

These come from the stories doc and from this repository's existing rules
(`docs/bite-evidence.md`, `docs/legal/`, `CONTRIBUTING.md`). They are tested
where a test can express them.

1. **Just text.** No app, no login, no forms. A phone number is the identity.
   The first text gets a useful answer, never a sign-up.
2. **Short, useful replies.** A text answers; the website carries depth. Every
   reply is at most 3 SMS segments (480 characters) unless it is a list the
   person asked for. Links only when they add something.
3. **Skippers win first.** Every skipper submission visibly helps that
   skipper's marketing: a credited post, a boat page, a weekly performance text.
4. **Never guess on rules.** Regulations come only from the rules table
   (`advisor_rules`), with a source and a reviewed date. The model may not
   state a size limit, bag limit, season or closure from its own memory. A rule
   past its review date is quoted with a "check CDFW" warning or not at all.
5. **Our own data.** Reports come from skippers who sent them to us. The
   advisor never republishes other aggregators' counts as ours. The existing
   scraped `landing-reports` feed stays separate and is cited as "reported by
   the landing" when used.
6. **No catch probability.** `docs/bite-evidence.md` rules apply: no bite
   score, no "hotspot" language, confidence ladder Insufficient / Low /
   Moderate. The advisor describes recent reported activity, not odds.
7. **Protect skippers' spots.** Area advice is general (reefs, depths, named
   public grounds). A skipper's text, photo EXIF or video never leaks a
   position. Photo EXIF is stripped before storage.
8. **People in photos are reviewed.** Any image classified as containing a
   person goes to the admin queue and is never auto-posted.
9. **Start local, configure outward.** Ports, species, rules and prompts are
   data (`catalog/`, `advisor_*` tables), keyed by region id, never hard-coded
   to Morro Bay.
10. **Cost ceilings on every paid call.** Per-contact daily caps, global daily
    caps, a kill switch, and analytics on every LLM, vision and Meta call,
    following `server/boat-lookup.ts` and `server/routes/boat.ts`.
11. **Privacy.** Phone numbers are stored hashed for lookup and encrypted for
    sending; message bodies and media live in D1 and a private R2 bucket,
    never in git, feeds or analytics. "Forget me" deletes everything about a
    number. Nothing identifying is ever written to Analytics Engine.

## Non-interference rules

The repository has two agents working in parallel and a deploy that runs on
every `main` commit. The advisor must be able to land over weeks without
blocking either.

- **Everything new lives under `server/advisor/`, `server/routes/advisor.ts`,
  `server/routes/admin.ts`, `web/advisor/`, `web/admin/`, `dist/advisor/`,
  `dist/admin/`, `catalog/advisor/`, `scripts/advisor/`, `tests/test_advisor_*.mjs`, `tests/fixtures/advisor/` and
  `docs/plans/text-advisor/`.** Shared files are touched only where listed in
  `01-architecture.md` § "Touch points in existing files", each in a small,
  obvious diff.
- **Dark by default.** The advisor routes answer 404 unless the repository
  variable `TEXT_ADVISOR_ENABLED=true` is deployed; the deploy adds its
  bindings only when `ENABLE_ADVISOR=true` (same pattern as `ENABLE_QUEUES`).
  All advisor settings are repository variables, never dashboard edits
  (01 § flags). Migrations add tables and columns only; no existing column
  changes.
- **No new paid service without the owner.** The Mac mini, the SIM, Twilio,
  a possible Sendblue trial, Meta ads: all owner steps.
- **Codex's lane is untouched.** No changes under `src/skippercast/`,
  `research/`, `regions/`, `atlas/`, the seafloor workflows or the daily data
  jobs. The one data job the advisor adds (`advisor-digest.yml`) is new.
- **The existing report scraper is not replaced.** Skipper-submitted reports
  are a new source (`skipper-reports`) alongside `landing-reports`.
- **Branch and PR rules in `AGENTS.md` apply to every task.** Rebase on
  `main`, one task per PR, independent review, no self-approval.

## Out of scope for v1

- Bookings, seat availability and payments.
- Paid subscription tiers (the free experience is designed so one can be added).
- Regions outside the Central Coast pilot beyond what configuration needs.
- Scraping or republishing other aggregators' fish counts.
- A native mobile app. WhatsApp. TikTok and YouTube Shorts reposting (SP-11).
- Regional social accounts (SP-12), the monthly contest (SP-13), voice notes
  (SC-6), follow alerts (FR-3), the weekly email roundup (WH-3), the weekly
  skipper performance text (SC-7) and tips/forecast posts (SO-3). Each is
  listed in the breakdown as "Next" with its prerequisites so it is a short
  follow-on, not a redesign.
