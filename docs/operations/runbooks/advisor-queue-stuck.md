# Runbook: Text Advisor messages are not being answered

**Symptom:** people text the advisor and get no reply while the relay is up; the admin Health view shows **stale queued** above 0 (inbound messages still `queued` after 2 minutes) or **failed today** climbing; Workers Logs show `advisor_consume_failed`, `advisor_enqueue_failed`, `advisor_inline_failed` or `advisor_batch` lines with `retried` or `failed`.
**Severity:** SEV2 while nobody gets an answer; SEV3 when only some turns fail. See [incident response](../incident-response.md).
**Owner:** repository owner. An agent can read logs, the health endpoints and D1, and open fix PRs.
**Not this runbook:** the relay is `down` in `GET /api/advisor/health` → [relay down](advisor-relay-down.md). Replies are wrong rather than missing → the soft switch below, then a prompt fix.

## How a message moves

The webhook stores the text in `advisor_messages` (`direction='in'`, status `queued`) and sends `{message_id}` to the `skippercast-advisor` queue, or runs the turn inline when the queue binding is missing or the send fails (`advisor_enqueue_failed`). The consumer marks the row `processing`, downloads media, runs the engine, sends the replies and marks it `done`. A turn that throws is retried (20 s × attempt, at most 300 s); after 3 retries the message goes to `skippercast-advisor-dlq`, whose consumer marks the row `failed` and sends the person one apology an hour at most. With `ADVISOR_REPLIES_ENABLED=false` the consumer marks rows `held` and sends nothing; held inbound rows are never replayed.

## Diagnose, in this order

1. **Switches.** `GET /api/admin/health` (or the Health view): `enabled`, `replies_enabled`. Replies off means rows are `held` by design.
2. **Where the rows are:**

   ```bash
   npx --yes wrangler@4.142.0 d1 execute skippercast --remote --command \
     "SELECT status, error, COUNT(*) n, MIN(created_at) oldest FROM advisor_messages WHERE direction='in' AND created_at > datetime('now','-1 day') GROUP BY status, error"
   ```

   - many `queued`, few `processing`: the consumer is not running → step 3.
   - `queued` with error `media-fetch` or `media-derive`: waiting for a download or for the media job's `public.jpg` → step 5.
   - `failed`: the DLQ took them → step 4.
   - `processing` for minutes: a turn is slow or the Worker hit its limit → step 4.
3. **Queue and consumer.** Cloudflare dashboard → Workers & Pages → Queues → `skippercast-advisor`: backlog and consumer errors. The consumer is the `skippercast` Worker itself (`wrangler.deploy.jsonc` `queues.consumers`); if it is missing, the last deploy ran without `ENABLE_ADVISOR=true` — set the variable and run **Actions → Deploy to Cloudflare**.
4. **Turn errors.** Workers Logs, filter `advisor_consume_failed`, `advisor_model_turn`, `advisor_global_cap`, `advisor_vision_failed`, `advisor_vision_provider_down`. Common causes:
   - the Anthropic API failing or rate-limited (HTTP 429/529 in the log reason): the engine already retries; wait, or lower traffic with the caps;
   - the global LLM cap spent (`advisor_global_cap`): people get the "swamped" line; raise `ADVISOR_GLOBAL_DAILY_LLM` only if the spend is expected;
   - a code fault after a deploy: [roll back the release](rollback-release.md).
5. **Media waits.** Health → **media jobs pending**. If it stays above 0, check **Actions → advisor-media**: the runner (`DATA_RUNNER`) is online, `R2_ADVISOR_TOKEN` is set, the last run is green ([runners](../runners.md)). A message waits for `public.jpg` at most three deliveries, then is answered anyway.

## Stop the bleeding

- **Soft switch** (wrong or runaway replies): `gh variable set ADVISOR_REPLIES_ENABLED --body false`, then `gh workflow run deploy-cloudflare.yml --ref main -f action=deploy`. Inbound texts are stored and acknowledged, nothing is sent, no model is called. Switching back on does not replay the `held` rows.
- **Hard switch** (security incident only): `gh variable set TEXT_ADVISOR_ENABLED --body false` and deploy. Every advisor route answers 404 and the relay's webhook deliveries fail.

## After

When rows are `done` again and **stale queued** is 0, decide what to do about people left without an answer: the admin queue's contact view shows each conversation, and "reply as team" answers one by hand. Record what happened in the incident note.
