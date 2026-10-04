// The only way advisor code writes a log line (docs/plans/text-advisor/02-data-model.md
// § Privacy invariants). One JSON object per line, with every string value,
// at any depth, scrubbed of anything that looks like a phone number first, so a
// number that slipped into an error message or a field never reaches Workers
// logs. tests/test_advisor_privacy.mjs checks that nothing else under
// server/advisor/ calls console.* directly.

export type AdvisorLogLevel = 'info' | 'warn' | 'error';

// A US number written as digits (optionally +1/1 first), or any E.164 number.
// Deliberately broad: a false positive costs a redacted id, a miss leaks a number.
const PHONE = /\+\d{10,15}|\+?1?\d{10}/g;
const MAX_DEPTH = 8;

/** `value` with every phone-like run in every string replaced by [redacted]; keys are scrubbed too. */
export function redact(value: unknown, depth = 0): unknown {
  if (typeof value === 'string') return value.replace(PHONE, '[redacted]');
  if (value === null || typeof value !== 'object') return typeof value === 'bigint' ? redact(String(value), depth) : value;
  if (depth >= MAX_DEPTH) return '[truncated]';
  if (value instanceof Error) return {name: value.name, message: redact(value.message, depth + 1)};
  if (Array.isArray(value)) return value.map(v => redact(v, depth + 1));
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value)) out[redact(k, depth + 1) as string] = redact(v, depth + 1);
  return out;
}

/** Writes {level, event, ...fields} as one redacted JSON line to console.log / warn / error. */
export function advisorLog(level: AdvisorLogLevel, event: string, fields: Record<string, unknown> = {}): void {
  const line = JSON.stringify(redact({...fields, level, event, scope: 'advisor'}), (_k, v) => typeof v === 'number' && !Number.isFinite(v) ? String(v) : v);
  if (level === 'error') console.error(line);
  else if (level === 'warn') console.warn(line);
  else console.log(line);
}
