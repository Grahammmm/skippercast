// After the run: print how many axe violations each page has by impact (and
// add them to the GitHub job summary). Only serious and critical ones fail a
// test today; the rest are the backlog this summary tracks.
import {appendFileSync, existsSync, readdirSync, readFileSync} from 'node:fs';
import {join} from 'node:path';
import {AXE_DIR} from './fixtures.ts';

interface Finding {id: string; impact: string | null; nodes: number}
interface Row {page: string; project: string; violations: Finding[]; incomplete: Finding[]}

export default function summary(): void {
  if (!existsSync(AXE_DIR)) return;
  const rows: Row[] = readdirSync(AXE_DIR).filter(n => n.endsWith('.json')).sort().map(n => JSON.parse(readFileSync(join(AXE_DIR, n), 'utf8')));
  const impacts = ['critical', 'serious', 'moderate', 'minor'];
  const lines = ['| Page | Viewport | ' + impacts.join(' | ') + ' | Violations | Needs review |', '| --- | --- | ' + impacts.map(() => '---').join(' | ') + ' | --- | --- |'];
  const list = (items: Finding[]) => items.map(v => `${v.id} (${v.nodes})`).join(', ') || '—';
  for (const r of rows) {
    const count = (impact: string) => r.violations.filter(v => v.impact === impact).length;
    lines.push(`| ${r.page} | ${r.project} | ${impacts.map(count).join(' | ')} | ${list(r.violations)} | ${list(r.incomplete || [])} |`);
  }
  const text = `\naxe (WCAG 2.1 A/AA and best practice): rules violated by impact, with affected nodes; serious and critical fail the run.\n${lines.join('\n')}\n`;
  console.log(text);
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, `### Accessibility (axe)\n${text}`);
}
