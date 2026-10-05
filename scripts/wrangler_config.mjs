#!/usr/bin/env node
// Write the deploy-time Wrangler config: wrangler.jsonc with the real D1 id and
// bucket names filled in, and optionally the custom domains the Worker serves.
// Usage:
//   node scripts/wrangler_config.mjs <d1-database-id> <feeds-bucket> [out] [domains]
// <domains> is a comma-separated host list (CUSTOM_DOMAINS, e.g.
// "skippercast.com,www.skippercast.com"); empty means workers.dev only.
// Optional features, switched on by environment variables (repository variables
// in the deploy workflow), add their bindings only when set to "true":
//   ENABLE_QUEUES     the trip-check queue and its dead-letter queue (server/trip-queue.ts)
//   ENABLE_ANALYTICS  the Workers Analytics Engine dataset skippercast_events (server/analytics.ts)
//   ENABLE_ADVISOR    the Text Advisor's private media bucket and queue pair (docs/plans/text-advisor/)
// and one switched off the same way:
//   WORKERS_INVOCATION_LOGS  "false" turns off Workers Logs' per-request invocation log (its
//                     message is the request URL, so a path secret such as the BlueBubbles webhook
//                     token would sit in it; docs/legal/threat-model.md § 9.1). Our own log lines,
//                     errors and exceptions are still kept.
// With ENABLE_ADVISOR, TEXT_ADVISOR_ENABLED and every ADVISOR_* variable set in
// the environment are copied into the Worker's vars (never a secret). The charter
// fleet has no bindings, so its FLEET_* variables are copied whenever set
// (docs/plans/charter-fleet/design.md § 16).
// Comments are removed by a string-aware scanner, so "//" inside a value (the
// $schema path, a URL) is never mistaken for a comment.
import {readFileSync, writeFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';

export function stripJsonComments(text) {
  let out = '', i = 0, inString = false;
  while (i < text.length) {
    const c = text[i], next = text[i + 1];
    if (inString) {
      out += c;
      if (c === '\\') { out += next ?? ''; i += 2; continue; }
      if (c === '"') inString = false;
      i++;
    } else if (c === '"') { inString = true; out += c; i++; }
    else if (c === '/' && next === '/') { while (i < text.length && text[i] !== '\n') i++; }
    else if (c === '/' && next === '*') { const end = text.indexOf('*/', i + 2); if (end < 0) throw Error('unterminated block comment'); i = end + 2; }
    else { out += c; i++; }
  }
  return out.replace(/,(\s*[}\]])/g, '$1');   // tolerate trailing commas
}

// A bare lower-case hostname with at least one dot: no scheme, port, path or wildcard.
const HOST = /^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;

export function customDomains(list = '') {
  const hosts = String(list).split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
  for (const host of hosts) if (!HOST.test(host)) throw Error(`not a custom domain hostname: ${host}`);
  return [...new Set(hosts)];
}

// Cloudflare Queues for trip checks (docs/cloudflare.md). The consumer takes up
// to 25 owners a batch, at most 5 batches at once; a message that fails 3 retries
// goes to the dead-letter queue, whose consumer logs and drops it.
export const TRIP_QUEUES = {
  producers: [{queue: 'skippercast-trip-checks', binding: 'TRIP_QUEUE'}],
  consumers: [
    {queue: 'skippercast-trip-checks', max_batch_size: 25, max_batch_timeout: 5, max_retries: 3, max_concurrency: 5,
      retry_delay: 30, dead_letter_queue: 'skippercast-trip-checks-dlq'},
    {queue: 'skippercast-trip-checks-dlq', max_batch_size: 25, max_batch_timeout: 30, max_retries: 0, max_concurrency: 1},
  ],
};

// Workers Analytics Engine: the dataset is created by Cloudflare on first write.
export const ANALYTICS_DATASETS = [{binding: 'ANALYTICS', dataset: 'skippercast_events'}];

// Text Advisor queue (docs/plans/text-advisor/01-architecture.md): its own consumer
// entry, not shared with trip checks. Up to 10 inbound messages a batch, at most 2
// batches at once; 3 retries 20 s apart, then the dead-letter queue, whose
// consumer logs, acks and sends at most one apology an hour.
export const ADVISOR_QUEUES = {
  producers: [{queue: 'skippercast-advisor', binding: 'ADVISOR_QUEUE'}],
  consumers: [
    {queue: 'skippercast-advisor', max_batch_size: 10, max_batch_timeout: 5, max_retries: 3, max_concurrency: 2,
      retry_delay: 20, dead_letter_queue: 'skippercast-advisor-dlq'},
    {queue: 'skippercast-advisor-dlq', max_batch_size: 25, max_batch_timeout: 30, max_retries: 0, max_concurrency: 1},
  ],
};
// Private bucket for advisor media (originals with EXIF stripped, derived files).
export const ADVISOR_BUCKET = {binding: 'ADVISOR_MEDIA', bucket_name: 'skippercast-advisor-media'};
// Worker secrets the advisor uses (01 secrets table). A deploy variable with one of
// these names is a mistake that would publish the secret in plain vars: refuse it.
// Only ADVISOR_* names can reach vars, so the ADVISOR_* secrets (ADVISOR_WEBHOOK_TOKEN,
// ADVISOR_PHONE_KEY) must reach cloudflare_deploy.sh under another source name, e.g.
// SECRET_ADVISOR_PHONE_KEY mapped in its secrets list, like WATCHDOG_GITHUB_TOKEN -> GITHUB_TOKEN.
export const ADVISOR_SECRETS = new Set(['ANTHROPIC_API_KEY', 'ADVISOR_WEBHOOK_TOKEN', 'BLUEBUBBLES_URL', 'BLUEBUBBLES_PASSWORD',
  'CF_ACCESS_CLIENT_ID', 'CF_ACCESS_CLIENT_SECRET', 'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_FROM',
  'HERMES_VISION_URL', 'HERMES_VISION_TOKEN', 'META_APP_ID', 'META_APP_SECRET', 'META_VERIFY_TOKEN', 'META_IG_USER_ID',
  'META_IG_TOKEN', 'META_PAGE_ID', 'META_PAGE_TOKEN', 'ADVISOR_PHONE_KEY', 'CF_ANALYTICS_TOKEN', 'R2_ADVISOR_TOKEN']);
// Advisor vars that are not ADVISOR_*-prefixed but belong to it (01 runtime-vars table).
const ADVISOR_VARS = new Set(['TEXT_ADVISOR_ENABLED', 'BLUEBUBBLES_PRIVATE_API']);

/** The advisor's plain vars from an environment: TEXT_ADVISOR_ENABLED, BLUEBUBBLES_PRIVATE_API and ADVISOR_*, non-empty only. */
export function advisorVars(environ = {}) {
  const vars = {};
  for (const [key, value] of Object.entries(environ).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) {
    if (!(ADVISOR_VARS.has(key) || key.startsWith('ADVISOR_'))) continue;
    if (ADVISOR_SECRETS.has(key)) throw Error(`${key} is a secret and must not be a deploy variable`);
    if (typeof value === 'string' && value.trim() !== '') vars[key] = value.trim();
  }
  return vars;
}

/** The charter fleet's plain vars from an environment: FLEET_*, non-empty only (server/fleet/settings.ts). */
export function fleetVars(environ = {}) {
  const vars = {};
  for (const [key, value] of Object.entries(environ).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0))
    if (key.startsWith('FLEET_') && typeof value === 'string' && value.trim() !== '') vars[key] = value.trim();
  return vars;
}

/** {queues, analytics, advisor} from environment variables; "true" (any case) turns a feature on. */
export function features(environ = {}) {
  const on = name => String(environ[name] ?? '').trim().toLowerCase() === 'true';
  const off = name => String(environ[name] ?? '').trim().toLowerCase() === 'false';
  return {queues: on('ENABLE_QUEUES'), analytics: on('ENABLE_ANALYTICS'), advisor: on('ENABLE_ADVISOR'), invocationLogs: !off('WORKERS_INVOCATION_LOGS')};
}

export function deployConfig(text, databaseId, bucket, domains = '', {queues = false, analytics = false, advisor = false, invocationLogs = true, environ = {}} = {}) {
  if (!/^[0-9a-f-]{36}$/.test(databaseId)) throw Error(`not a D1 database id: ${databaseId}`);
  if (!/^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$/.test(bucket)) throw Error(`not an R2 bucket name: ${bucket}`);
  const config = JSON.parse(stripJsonComments(text));
  config.d1_databases[0].database_id = databaseId;
  config.r2_buckets[0].bucket_name = bucket;
  // The workers.dev address stays on as the staging and fallback URL, with or
  // without custom domains (Wrangler would otherwise turn it off once routes exist).
  config.workers_dev = true;
  const hosts = customDomains(domains);
  if (hosts.length) config.routes = hosts.map(pattern => ({pattern, custom_domain: true}));
  if (queues) config.queues = structuredClone(TRIP_QUEUES);
  if (analytics) config.analytics_engine_datasets = structuredClone(ANALYTICS_DATASETS);
  // Workers Logs keeps our own lines; only the automatic per-request record (with the URL) goes.
  if (!invocationLogs) config.observability = {...config.observability, logs: {...config.observability?.logs, invocation_logs: false}};
  if (advisor) {
    const extra = structuredClone(ADVISOR_QUEUES);
    config.queues = config.queues
      ? {producers: [...config.queues.producers, ...extra.producers], consumers: [...config.queues.consumers, ...extra.consumers]}
      : extra;
    config.r2_buckets.push({...ADVISOR_BUCKET});
    config.vars = {...config.vars, ...advisorVars(environ)};
  }
  const fleet = fleetVars(environ);
  if (Object.keys(fleet).length) config.vars = {...config.vars, ...fleet};
  return config;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [databaseId, bucket, out = 'wrangler.deploy.jsonc'] = process.argv.slice(2);
  const enabled = features(process.env);
  const config = deployConfig(readFileSync('wrangler.jsonc', 'utf8'), databaseId || '', bucket || '', process.argv[5] || '', {...enabled, environ: process.env});
  writeFileSync(out, JSON.stringify(config, null, 2) + '\n');
  const on = Object.keys(enabled).filter(k => enabled[k]);
  console.log(`Wrote ${out}${on.length ? ` (with ${on.join(', ')})` : ''}`);
}
