// Read-only check: does /api/coast/report still come from the old Fish service?
// Usage: node scripts/check_coast_report_source.mjs [--from-file <saved header block>]
// Exit 0 PASS, 1 FAIL, 2 could not read. Changes no switch; sends nothing.
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const URL_ = 'https://skippercast.com/api/coast/report';

export function parseUpstream(value) {
  if (value == null || !String(value).trim()) return [];
  return String(value).split(',').map((s) => s.trim()).filter(Boolean).map((s) => {
    const i = s.indexOf('=');
    return i < 0 ? { name: s.toLowerCase(), value: '', bad: s }
      : { name: s.slice(0, i).trim().toLowerCase(), value: s.slice(i + 1).trim() };
  });
}

export function verdict(value) {
  const entries = parseUpstream(value);
  if (!entries.length) return { lines: [], ok: false, failures: ['header missing'] };
  const report = entries.find((e) => e.name === 'report');
  const reportOk = report?.value === 'skippercast';
  const lines = [], failures = [];
  for (const e of entries) {
    const fish = e.value.startsWith('fish');
    const demote = fish && reportOk; // other sources on Fish: note only
    lines.push(`${demote ? 'note: ' : ''}${e.name}: ${e.value}`);
    if (e.bad) failures.push(`unreadable entry ${e.bad}`);
    else if (fish && !demote) failures.push(`${e.name}=${e.value}`);
  }
  if (!report) failures.push('report entry missing');
  else if (!reportOk && !failures.some((f) => f.startsWith('report='))) failures.push(`report=${report.value}`);
  return { lines, ok: failures.length === 0, failures };
}

function headerFromBlock(text) {
  const rows = text.replace(/\r/g, '').split('\n');
  const at = rows.findIndex((r) => /^x-coast-upstream:/i.test(r));
  if (at < 0) return null;
  let v = rows[at].replace(/^[^:]*:/, '');
  for (let i = at + 1; i < rows.length && /^[ \t]/.test(rows[i]); i++) v += rows[i];
  return v.trim();
}

export async function run(argv, { fetchImpl = fetch, readFile = (p) => readFileSync(p, 'utf8'), out = console.log, err = console.error } = {}) {
  let value;
  if (argv.length === 0) {
    try {
      const res = await fetchImpl(URL_, { method: 'GET', redirect: 'manual', credentials: 'omit',
        headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(15000) });
      await res.body?.cancel();
      if (res.status !== 200) throw new Error(`HTTP ${res.status}`);
      value = res.headers.get('x-coast-upstream');
    } catch (e) { err(`could not read the report: ${e.message}`); return 2; }
  } else if (argv.length === 2 && argv[0] === '--from-file') {
    try { value = headerFromBlock(readFile(argv[1])); }
    catch (e) { err(`could not read the report: ${e.message}`); return 2; }
  } else { err('usage: check_coast_report_source.mjs [--from-file <header block>]'); return 2; }
  const v = verdict(value);
  for (const l of v.lines) out(l);
  out(v.ok ? 'PASS' : `FAIL: ${v.failures.join('; ')}`);
  return v.ok ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) process.exitCode = await run(process.argv.slice(2));
