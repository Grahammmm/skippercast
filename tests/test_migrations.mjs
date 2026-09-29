import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,readdirSync,existsSync,mkdtempSync,cpSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';

const root=fileURLToPath(new URL('..',import.meta.url)),drizzle=join(root,'drizzle');
const journal=JSON.parse(readFileSync(join(drizzle,'meta','_journal.json'),'utf8'));

test('the drizzle journal lists every migration file, in order, with its snapshot',()=>{
  const files=readdirSync(drizzle).filter(f=>f.endsWith('.sql')).sort();
  const tags=journal.entries.map(e=>e.tag);
  assert.deepEqual(journal.entries.map(e=>e.idx),tags.map((_,i)=>i),'journal idx values are 0..n-1 in order');
  assert.deepEqual(files,tags.map(t=>t+'.sql').sort(),'every .sql file is in the journal and every entry has a file');
  for(const [i,tag] of tags.entries()){
    assert.ok(tag.startsWith(String(i).padStart(4,'0')+'_'),`${tag} is numbered for position ${i}`);
    assert.ok(existsSync(join(drizzle,'meta',`${tag.slice(0,4)}_snapshot.json`)),`${tag} has a schema snapshot`);
  }
});

test('db/schema.ts and the committed migrations agree (drizzle-kit generate has nothing to add)',t=>{
  const kit=join(root,'node_modules','.bin','drizzle-kit');
  if(!existsSync(kit))return t.skip('drizzle-kit is not installed (run pnpm install)');
  // drizzle-kit resolves --out relative to its working directory (and exits 0 on
  // errors), so run it inside a scratch copy and check its output as well as files.
  const work=mkdtempSync(join(tmpdir(),'skippercast-drizzle-')),out=join(work,'drizzle');
  try{
    cpSync(drizzle,out,{recursive:true});
    const run=spawnSync(kit,['generate','--dialect','sqlite','--schema',join(root,'db','schema.ts'),'--out','drizzle'],{cwd:work,encoding:'utf8'});
    const output=run.stdout+run.stderr;
    assert.equal(run.status,0,output);assert.doesNotMatch(output,/error/i);
    assert.match(output,/no schema changes/i,output);
    assert.deepEqual(readdirSync(out).filter(f=>f.endsWith('.sql')).sort(),readdirSync(drizzle).filter(f=>f.endsWith('.sql')).sort(),'schema changed without a committed migration:\n'+output);
    assert.equal(readFileSync(join(out,'meta','_journal.json'),'utf8'),readFileSync(join(drizzle,'meta','_journal.json'),'utf8'),'journal unchanged');
  }finally{rmSync(work,{recursive:true,force:true});}
});
