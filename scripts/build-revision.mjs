// Build-time Git provenance for /api/health (S4-48). Run by scripts/build-worker.mjs only; never by the
// Worker or a request. Observational: any failure yields nulls and never fails the build.
import {execFileSync} from 'node:child_process';

const OPTIONS = root => ({cwd: root, encoding: 'utf8', timeout: 2000, maxBuffer: 65536, stdio: ['ignore', 'pipe', 'ignore']});
const UNKNOWN = {revision: null, revision_dirty: null};

export function readBuildRevision(root, run = execFileSync) {
  try {
    const revision = String(run('git', ['rev-parse', '--verify', 'HEAD'], OPTIONS(root))).trim();
    if (!/^[0-9a-f]{40}$/.test(revision)) return {...UNKNOWN};
    // Tracked staged/unstaged changes only; untracked files are outside this flag.
    const status = String(run('git', ['status', '--porcelain', '--untracked-files=no'], OPTIONS(root)));
    return {revision, revision_dirty: status.length > 0};
  } catch {
    return {...UNKNOWN};
  }
}
