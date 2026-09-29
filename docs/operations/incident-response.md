# Incident response

How SkipperCast handles something going wrong in production: how bad it is, who acts, where it is recorded, and how we learn from it. SkipperCast is run by one owner with AI agents (Claude, Codex) preparing changes; this process is sized for that.

## Severity levels

| Level | Meaning | Examples | Response |
| --- | --- | --- | --- |
| **SEV1** | People's private data exposed or lost, a credential that writes data or spends money is exposed, or the app shows something dangerously wrong as if it were current | One person can read another's trips; forged identity accepted; a leaked `CLOUDFLARE_API_TOKEN`; a forecast or rule shown as fresh when it is not | Start now, any hour. Contain first (revoke, roll back, switch off the feature), then fix. |
| **SEV2** | A core public feature is broken or stale for everyone | Live feed more than 3 hours stale; map or forecast fails to load; `/feeds/*` failing; a deploy broke the site; loss of saved trips | Start the same day. |
| **SEV3** | Degraded or partial | One region or source failing; push delivery held; AI boat lookup down; Cloudflare staging broken while skippercast.com is fine | Next working session. |
| **SEV4** | Cosmetic or internal | A research workflow red; a doc wrong | Normal issue and PR. |

When unsure, pick the higher level; downgrade later in the timeline. Fail-closed behaviour the app already shows to users (a source labelled stale, a rule withheld pending review) is working as designed, not an incident, unless it lasts long enough to hide the product.

## Roles

- **Incident lead: the repository owner.** Decides severity, approves every production change (merge, deploy, rollback, secret change, database restore) and all communication.
- **Agents** diagnose, draft fixes as PRs, draft the timeline and postmortem, and run read-only commands. Agents never push to `main`, change secrets, restore databases or post outside the incident issue.

## Runbooks

| Situation | Runbook |
| --- | --- |
| Live feed stale; `feed-stale` issue open | [feed-stale](runbooks/feed-stale.md) |
| `/feeds/*` failing or R2 behind GitHub | [r2-outage](runbooks/r2-outage.md) |
| Private records lost or corrupted; D1 down | [d1-restore](runbooks/d1-restore.md) |
| Secret leaked, expired or revoked | [secrets-rotation](runbooks/secrets-rotation.md) |
| Trip alerts late or missing; `trip_check_dead_letter` in Worker logs | [trip-checks](runbooks/trip-checks.md) |
| A deploy broke the site | `docs/operations/runbooks/rollback-release.md`, added by PR #26 ([P0-03]); until it merges, redeploy the previous good `main` commit with **Actions → Deploy to Cloudflare → Run workflow** from that commit, and republish the previous version on ChatGPT Sites |

Background: [production operations](../production-operations.md) and [Cloudflare](../cloudflare.md).

## During an incident

1. **Open the record.** One GitHub issue per incident, title `Incident: <what users see>`, label `incident` plus the severity (`sev1`…`sev4`; create the labels on first use). The automatic `feed-stale` issue counts as the record for a stale feed.
   - The repository is public. **Never put personal data, tokens, database exports, request logs with owners, or security details that are still exploitable in the issue.** For SEV1 security issues, keep the working notes private (a draft security advisory: **Security → Advisories → New draft**) and open the public issue only after the fix.
2. **Contain.** Use the runbook's quickest safe lever: roll back the Worker, unbind R2, delete an exposed secret, switch off a feature (for example remove `ANTHROPIC_API_KEY`; after PR #29, set `BOAT_LOOKUP_ENABLED=false`). Prefer switching something off to leaving it wrong.
3. **Keep a timeline** in the issue as you go: UTC time, what was observed, what was done, by whom. Paste commands and short outputs, not screenshots.
4. **Fix** through a PR that passes CI, as usual. An emergency does not skip CI; a rollback is the fast path, not a direct push.
5. **Verify** with the runbook's Verify section, then watch one more scheduled cycle (30 minutes for live data) before closing.

## Communication

- **Status:** SkipperCast has no status page yet. The incident issue is the public record. For SEV1 and SEV2 the owner decides whether to add a notice to the app's Guide view.
- **Users:** the app stores no email addresses (sign-in is ChatGPT's; the Worker keeps only an opaque owner id), so affected people cannot be emailed directly. A privacy incident may still carry legal notification duties (California breach notification, CCPA): the owner consults counsel before saying anything about personal data.
- **Tone:** state what users see, what they should do (for example "check conditions with NOAA directly until this is fixed"), and when the next update will come. Never overstate: the product's rule is that stale or missing evidence is shown as such.

## After an incident

- **Postmortem** is required for every SEV1 and SEV2, and for any SEV3 that recurs. Write it within five working days, in the incident issue (or the private advisory for security issues, published after the fix).
- **Blameless:** describe what the system allowed, not who slipped. The action items change the system: a test, a check, an alert, a runbook fix.
- Each action item becomes an issue or PR, linked from the postmortem. Update the runbook you used if any step was wrong or missing.

## Timeline template

```text
YYYY-MM-DD HH:MM UTC  Detected: <how: freshness issue, user report, workflow failure>
YYYY-MM-DD HH:MM UTC  Severity SEVn declared by <owner>
YYYY-MM-DD HH:MM UTC  <observation or action; command and short output>
YYYY-MM-DD HH:MM UTC  Contained: <what stopped the impact>
YYYY-MM-DD HH:MM UTC  Resolved: <verification that passed>
```

## Postmortem template

```markdown
# Postmortem: <title>

- **Severity:** SEVn · **Status:** draft | final
- **Detected / resolved:** <UTC times> · **User impact duration:** <h:mm>
- **Incident issue:** #<n>

## Summary
Two or three sentences: what users experienced and why.

## Impact
Who and what was affected (features, regions, number of users or records if known). What was *not* affected.

## Timeline
Paste the incident timeline (UTC).

## Root cause
The technical chain of events. Link the code, workflow or config lines.

## What went well / what went badly
Detection, containment, runbooks, tooling.

## Why it was not caught earlier
Which test, check or alert should have caught it, and why it didn't.

## Action items
| Action | Type (prevent / detect / mitigate / docs) | Issue or PR | Owner |
| --- | --- | --- | --- |
```
