# Runbook: rotate a secret

**Symptom:** a secret leaked or may have (committed, pasted into an issue or log, a laptop lost, a collaborator removed), a provider revoked it, it expired, or a scheduled rotation is due. Jobs failing with `could not verify CLOUDFLARE_API_TOKEN`, Wrangler `Authentication error`, a watchdog log `dispatch-failed-401`, or AI boat lookups answering 502 also point here.
**Severity:** SEV1 if a secret that can write data or spend money is known to be exposed; SEV3 for an expired or revoked secret; planned rotation is not an incident.
**Owner:** repository owner. Only the owner holds the Cloudflare, GitHub and Anthropic accounts.

## Inventory

| Secret | Stored in | Used by | Grants |
| --- | --- | --- | --- |
| `CLOUDFLARE_API_TOKEN` | GitHub Actions secret | `deploy-cloudflare.yml`, `live-conditions.yml`, `daily-data.yml`, `forecast-tiles.yml`, `seafloor.yml` (via `scripts/cloudflare_deploy.sh`, `scripts/publish_r2.py`, `src/skippercast/seafloor/publish.py`) | Workers, D1 and R2 edit on the account; its id and SHA-256 are also the R2 S3 key pair |
| `CLOUDFLARE_ACCOUNT_ID` | GitHub Actions secret | same | Not a credential; an identifier |
| `ANTHROPIC_API_KEY` | GitHub Actions secret → Worker secret (uploaded by `cloudflare_deploy.sh`) | `server/boat-lookup.ts` via `/api/boat/lookup` | Spends Anthropic credit |
| `WATCHDOG_GITHUB_TOKEN` | GitHub Actions secret → Worker secret `GITHUB_TOKEN` | `server/watchdog.ts` | Fine-grained token: Actions read and write on this repository only |
| `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` | `secrets/vapid.json` in the private backup bucket (`cloudflare_deploy.sh` generates it on the first deploy and reads it back on every later one), or GitHub Actions secrets of the same names, which take precedence → Worker secrets | `server/trips.ts` `deliver()`; `/api/session` returns the public key | Signs Web Push messages to subscribed devices |
| `EXTRA_ORIGINS` | GitHub Actions variable → Worker secret | `server/http.ts` `requireOrigin` (origins from `server/middleware/context.ts`) | Not a credential; adds allowed origins |

No secret exists for: the scheduler (GitHub OIDC; the policy is the public `deployments/production.json`, see `server/job-auth.ts`), the Actions `github.token` (issued per run), D1 and R2 bindings (granted by the Worker's configuration). Repository variables `CLOUDFLARE_SITE_URL` and, after PR #30, `FEEDS_PUBLIC_BASE` are not secrets.

## General order

- **Planned rotation or suspected leak:** create the new secret → install it everywhere → verify → revoke the old one. No downtime.
- **Confirmed leak of a secret that writes data or spends money:** revoke first, accept that the jobs using it fail until the new one is installed, then continue as above.
- After any leak, check the provider's audit log for use you don't recognise: Cloudflare (**Manage Account → Audit Log**), GitHub (**Settings → Security log** and the repository's **Actions** runs), Anthropic Console usage.
- A secret committed to git stays in history even after a revert. Rotate it; do not rely on rewriting history. `python3 scripts/check_repository.py` flags common credential shapes before commit.

Commands below assume the GitHub CLI (`gh`) authenticated as the owner, and:

```bash
W="npx --yes wrangler@4.142.0"
export CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=...   # the token being installed, for Wrangler steps
```

`gh secret set NAME` and `wrangler secret put NAME` read the value from standard input, so it never lands in shell history when you paste it at the prompt.

## CLOUDFLARE_API_TOKEN

1. Cloudflare dashboard → **My Profile → API Tokens → Create Token** → template **Edit Cloudflare Workers**; add **Account · D1 · Edit** and **Account · Workers R2 Storage · Edit**; restrict to the SkipperCast account ([Cloudflare setup](../../cloudflare.md)).
2. Check it: `curl -fsS -H "Authorization: Bearer <new token>" https://api.cloudflare.com/client/v4/user/tokens/verify` → `"status":"active"`.
3. Install: `gh secret set CLOUDFLARE_API_TOKEN`.
4. Verify every consumer: `gh workflow run deploy-cloudflare.yml --ref main` (deploy) and `gh workflow run live-conditions.yml --ref main` (R2 publish); both must be green and the live run must log `R2 skippercast-feeds/conditions: ... uploaded`.
5. Revoke the old token in the dashboard (**API Tokens → ... → Delete**).

Until step 3, R2 publication fails; on `main` that is a warning and GitHub branches stay current (see [R2 outage](r2-outage.md) for catching up R2).

## ANTHROPIC_API_KEY

1. Emergency stop (spend or abuse): remove the Worker secret so `/api/boat/lookup` answers 503 "not configured", and the GitHub secret so the next deploy doesn't restore it:
   ```bash
   $W secret delete ANTHROPIC_API_KEY --name skippercast
   gh secret delete ANTHROPIC_API_KEY
   ```
   After PR #29 ([P0-08]) merges, setting the Worker variable `BOAT_LOOKUP_ENABLED` to `false` also stops lookups without touching the key.
2. Anthropic Console → **API Keys** → create a new key.
3. Install: `gh secret set ANTHROPIC_API_KEY`, then either run the deploy workflow (it uploads the secret) or `$W secret put ANTHROPIC_API_KEY --name skippercast`.
4. Verify: a signed-in boat lookup succeeds (not available on Cloudflare until sign-in exists; there, check that `$W secret list --name skippercast` lists the name).
5. Revoke the old key in the Console.

## WATCHDOG_GITHUB_TOKEN

1. GitHub → **Settings → Developer settings → Fine-grained tokens → Generate**: repository access *Only Grahammmm/skippercast*, permission **Actions: Read and write**, nothing else; set an expiry.
2. Check it: `curl -fsS -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer <new token>" https://api.github.com/repos/Grahammmm/skippercast/actions/workflows/live-conditions.yml` → `200`.
3. Install: `gh secret set WATCHDOG_GITHUB_TOKEN`, then run the deploy workflow, or `$W secret put GITHUB_TOKEN --name skippercast` (the Worker secret is named `GITHUB_TOKEN`).
4. Verify: `$W tail skippercast --format pretty --search "Live feed watchdog"` shows no `dispatch-failed-401` over the next stale period; `$W secret list --name skippercast` lists `GITHUB_TOKEN`.
5. Delete the old token in GitHub settings.

## VAPID key pair

Where the pair lives: the deploy script keeps it at `r2://skippercast-backups/secrets/vapid.json` (generated once by the first deploy that found none, read back by every deploy since) unless both `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` are set as GitHub Actions secrets, which win. A read that fails for any reason other than a missing object stops the deploy rather than generating a new pair over the stored one.

Rotate only if the private key leaked: every existing push subscription is bound to the old public key, so each person must turn notifications on again.

1. Either delete the stored object so the next deploy generates a fresh pair (`$W r2 object delete skippercast-backups/secrets/vapid.json --remote`, then run the deploy workflow and skip to step 3), or generate a pair yourself (Node 22; prints JSON with both values):
   ```bash
   node --input-type=module -e "const k=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},true,['sign']);const b=u=>Buffer.from(u).toString('base64url');console.log(JSON.stringify({VAPID_PUBLIC_KEY:b(await crypto.subtle.exportKey('raw',k.publicKey)),VAPID_PRIVATE_KEY:(await crypto.subtle.exportKey('jwk',k.privateKey)).d}))"
   ```
   The public key is 87 characters and the private key 43, the formats `@block65/webcrypto-web-push` expects.
2. If you generated the pair yourself, set both as GitHub Actions secrets (`gh secret set VAPID_PUBLIC_KEY` and `gh secret set VAPID_PRIVATE_KEY`) and run the deploy workflow; the deploy uploads them to the Worker and the smoke test checks that `/api/session` serves the public key.
3. Old subscriptions now fail; deliveries are recorded as `failed` and alerts as `held`, which makes `scripts/check_saved_trips.py` fail the live job. Remove them in the database that holds them (`DELETE FROM subscriptions`; see [D1 restore](d1-restore.md) for running SQL) and tell users to re-enable notifications from the app. In-app assessments keep working without push.
4. Verify: `curl -fsS https://skippercast.com/api/session` returns the new `publicKey`; enabling notifications on a test device and saving a trip produces a delivered alert on the next check.

## ADVISOR_WEBHOOK_TOKEN (Text Advisor)

The BlueBubbles webhook (and the Twilio ones, after a port) carries this token in its URL path, because BlueBubbles cannot send a header or sign its requests ([threat model § 9.1](../../legal/threat-model.md#91-inbound-webhooks)). Our own logs never hold it (`redactPath` in `server/middleware/error.ts`, and the advisor's routes answer their own errors), but Cloudflare's **Workers Logs invocation log** records every request URL, so anyone with log access to the account can read it until the logs age out. Keep account membership minimal; set the repository variable `WORKERS_INVOCATION_LOGS=false` to stop the invocation log entirely (our own log lines stay; `scripts/wrangler_config.mjs`). Rotate it on a schedule (every 90 days), whenever someone leaves the Cloudflare account, and at once if it may have leaked: anyone who has it can post texts as any contact (§ 9.1).

Rotation drops the deliveries that arrive between the deploy and the BlueBubbles change (each answers `401`, and BlueBubbles is not known to retry), so do it at a quiet hour and keep the gap to a minute or two.

1. Make the new token: `openssl rand -base64 32 | tr '+/' '-_' | tr -d '='` (URL-safe, 43 characters).
2. Install: `gh secret set ADVISOR_WEBHOOK_TOKEN`, then upload it at once with `$W secret put ADVISOR_WEBHOOK_TOKEN --name skippercast` (a later deploy uploads the same value from the GitHub secret).
3. Straight away, on the Mac: **BlueBubbles → API & Webhooks**, edit the webhook's URL to `https://skippercast.com/api/advisor/inbound/bluebubbles/<new token>` and save. After a Twilio port, also change the messaging and status callback URLs in the Twilio console ([port to Twilio](advisor-port-to-twilio.md)).
4. Verify: text the advisor's number from your phone and get the reply; `$W tail skippercast --format pretty --search advisor_webhook_unauthorized` shows no new lines after step 3.
5. Catch up: open Messages on the Mac and look for texts received between steps 2 and 3; answer them by hand from the admin queue or ask the sender to text again.
6. The old token is now useless, including the copies in Workers Logs; nothing to revoke elsewhere.

## EXTRA_ORIGINS

Not secret. Change the repository variable (`gh variable set EXTRA_ORIGINS`) and run the deploy workflow. Each entry must match `https://[a-z0-9.-]+` or the Worker ignores it.

## Verify (any rotation)

- The workflows that use the secret are green on their next run.
- `python3 scripts/check_feed_freshness.py --max-age-hours 3` passes.
- The old secret is revoked at the provider, not only replaced.

## Rollback

A revoked secret cannot be restored. If the new secret is wrong, create another one; do not re-enable a leaked one.

## Escalate

Provider support (Cloudflare, GitHub, Anthropic) if the dashboard will not revoke a credential or the audit log shows use you can't explain. Unexplained use of a data-writing secret is SEV1.

## Postmortem

Required for any leak. Use the [postmortem template](../incident-response.md#postmortem-template).
