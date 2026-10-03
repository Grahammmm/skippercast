# 0007. Text Advisor: an owned number with a self-hosted iMessage relay, Twilio as the fallback, and a two-provider vision chain

- **Status:** Accepted (owner decision, 2026-10-03)
- **Date:** 2026-10-03

## Context

- The owner is building the Text Advisor: a fishing advisor people text,
  through which skippers submit catch counts and photos that feed the
  website and SkipperCast's social accounts (plan: `docs/plans/text-advisor/`).
- Most US anglers and skippers are on iPhone. The owner wants iMessage
  quality (full-size photos, blue bubbles) but has one hard constraint:
  **never tell users a new phone number**, whatever breaks.
- There is no official iMessage business API. Hosted iMessage services
  (Sendblue, LoopMessage) issue their own numbers or sender names; whether a
  number can be ported out of them is not documented. A self-hosted relay
  (BlueBubbles on a Mac) uses a number registered through an iPhone with a
  SIM, which the owner can own and can later port to Twilio as SMS/MMS.
- Nothing in this repository reads images. The owner's Hermes machine will
  host a local classifier for privacy and cost, but its interface does not
  exist yet. The feature cannot wait on it.
- The Worker already has a pattern for paid model calls with kill switches,
  caps and analytics (`server/boat-lookup.ts`).

## Decision

1. **One owned number.** SkipperCast buys a mobile number on a real SIM,
   held by a spare iPhone signed into a dedicated Apple Account, with a Mac
   mini on the same account running the BlueBubbles server. iMessage and
   SMS both go through that relay from the one number. The number is the
   only identity ever published.
2. **Twilio is the fallback on the same number, one way.** If the relay
   fails for good, iMessage is deregistered and the number is ported to
   Twilio for SMS/MMS. Users keep the number and lose blue bubbles. The
   runbook for this is a deliverable of the feature. 10DLC registration is
   completed in advance so the switch is not blocked by carrier vetting.
3. **The Worker talks to channels through one adapter interface** with
   BlueBubbles, Twilio and web implementations, selected by configuration,
   so the switch is a variable change. WhatsApp is a later adapter.
4. **Vision is a provider chain** behind one interface: the Hermes local
   classifier first when configured and healthy, Claude vision otherwise.
   Claude vision is implemented and tested in full; Hermes is built to a
   contract published in the plan and is optional.
5. **Everything ships dark** behind `ENABLE_ADVISOR` and
   `TEXT_ADVISOR_ENABLED`, as new tables, routes and modules, with no
   changes to the trip planner, the data pipelines or the Codex seafloor
   work.

## Consequences

- (+) The number is an asset the owner controls; no vendor holds the
  customer relationship.
- (+) Near-zero per-message cost; one Mac mini and one cheap line.
- (+) The fallback is proven technology (number porting, Twilio SMS), not a
  hope.
- (+) Fish ID and count-board reading work on day one with Claude; Hermes
  can lower cost later without a code change elsewhere.
- (–) A Mac and an iPhone in the owner's house are production
  infrastructure: power, Wi-Fi, macOS updates and Apple Account hygiene
  become operations work (runbooks, watchdog, alerts).
- (–) Apple can deregister or suspend the account; automated volume must
  stay modest and opt-outs must be honoured by us (Twilio's automatic STOP
  handling does not cover iMessage).
- (–) The fallback is one way: once ported to Twilio the number can never be
  an iMessage handle again.
- (–) Two vision providers mean two prompts or models to keep consistent;
  the shared result schema and conformance script are the mitigation.

## Alternatives

- **Hosted iMessage API (Sendblue, LoopMessage), ~$100/month.** Simplest to
  run; rejected for v1 because number ownership and port-out are
  undocumented, so a vendor change could mean a new number. Revisit if a
  vendor documents porting in and out.
- **Twilio only from day one.** Cheapest to operate; rejected because
  photo quality and the iPhone-native feel matter for skippers and the
  relay keeps the same number as the fallback anyway.
- **Build vision only in the Worker with Claude.** Would have been simpler;
  rejected because the owner wants local classification available for cost
  and privacy, and the chain costs little once the interface exists.
- **Run the advisor as a separate service on Hermes.** Rejected: splits the
  product across two deployments, two auth systems and two data stores for
  no gain; the Worker already has the data, the feeds and the deploy.

## Links

- Plan: `docs/plans/text-advisor/README.md` and `03-channels.md`, `07-vision.md`.
- Related: ADR 0006 (accounts), `docs/legal/threat-model.md` (section added
  by TA-C5), `docs/operations/runbooks/advisor-port-to-twilio.md` (TA-C7).
