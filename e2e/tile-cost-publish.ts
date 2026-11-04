// BF-tile-cost: how the per-project audit workers publish one complete report.
// Each project's worker saves only its own rows file; tile-cost.json is
// written only when every configured project's file is present and full.
// Every write goes through a writer-private temp file and an atomic rename,
// so two workers never share a temp file and a reader (or a later writer)
// never sees, or replaces the report with, a partial run.
import {existsSync, mkdirSync, readFileSync, renameSync, writeFileSync} from 'node:fs';
import {dirname, join} from 'node:path';
import type {Row} from './tile-cost.ts';

export interface PublishPlan {runDir: string; out: string; projects: string[]; perProject: number; commit: string}

export function writeAtomic(path: string, body: string, writer: string | number = process.pid): void {
  mkdirSync(dirname(path), {recursive: true});
  const tmp = `${path}.${writer}.tmp`;
  writeFileSync(tmp, body);
  renameSync(tmp, path);
}

/**
 * Save one project's rows; publish the complete run if every project has
 * finished. Returns the published rows, or null while a project is missing.
 * Two finishers both publish the same complete document; a retried project
 * replaces its own file rather than adding rows.
 */
export function saveAndPublish(plan: PublishPlan, project: string, rows: Row[], writer: string | number = process.pid): Row[] | null {
  if (rows.length !== plan.perProject) throw new Error(`${project}: ${rows.length} rows, expected ${plan.perProject}`);
  writeAtomic(join(plan.runDir, `${project}.json`), JSON.stringify(rows), writer);
  const files = plan.projects.map(name => join(plan.runDir, `${name}.json`));
  if (!files.every(path => existsSync(path))) return null;
  const all: Row[] = files.flatMap(path => JSON.parse(readFileSync(path, 'utf8')) as Row[]);
  for (const name of plan.projects) {
    const n = all.filter(r => r.project === name).length;
    if (n !== plan.perProject) throw new Error(`${name}: ${n} rows in the run, expected ${plan.perProject}`);
  }
  writeAtomic(plan.out, JSON.stringify({schema: 'tile-cost-v1', commit: plan.commit, rows: all}, null, 1), writer);
  return all;
}
