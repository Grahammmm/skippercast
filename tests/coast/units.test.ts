// RF1140-5: packages/coast reads its unit factors from one module, with values unchanged.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,readdirSync} from 'node:fs';
import {join,relative} from 'node:path';
import {fileURLToPath} from 'node:url';
import {FEET_PER_M,KNOTS_PER_MS} from '../../packages/coast/src/units.ts';
import {vectorReading} from '../../packages/coast/src/map/surface-field.ts';

const SRC=fileURLToPath(new URL('../../packages/coast/src/',import.meta.url));
const UNIT_LITERAL=/3\.2808|0\.3048|1\.9438/;
function unitLiterals(file:string,text:string):string[]{
 return text.split('\n').flatMap((line,i)=>UNIT_LITERAL.test(line)?[`${file}:${i+1}`]:[]);
}
function sources(dir:string):string[]{
 return readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?sources(join(dir,e.name)):e.name.endsWith('.ts')?[join(dir,e.name)]:[]);
}

test('unit factors keep the exact values rendered today',()=>{
 assert.equal(FEET_PER_M,3.28084);assert.equal(KNOTS_PER_MS,1.943844492);
});
test('no coast source outside units.ts spells out a unit factor',()=>{
 const files=sources(SRC).map(f=>relative(SRC,f)).filter(f=>f!=='units.ts');
 assert.ok(files.includes('coast3d/viewer.ts')&&files.includes('bottom/loader.ts')&&files.includes('map/surface-field.ts'));
 assert.deepEqual(files.flatMap(f=>unitLiterals(f,readFileSync(join(SRC,f),'utf8'))),[]);
});
test('the literal guard reports the file and line of a planted factor',()=>{
 assert.deepEqual(unitLiterals('planted.ts','const a=1;\nconst ft=x*3.28084;\nconst m=y*0.3048;\nconst kt=z*1.943844492;'),['planted.ts:2','planted.ts:3','planted.ts:4']);
 assert.deepEqual(unitLiterals('clean.ts','const ft=x*FEET_PER_M;\nconst n=3.28;\nconst k=1.94;'),[]);
});
test('current readings give the same answers through the shared factor',()=>{
 assert.equal(vectorReading([0,1]).speedKnots,KNOTS_PER_MS);
 assert.equal(vectorReading([3,4]).speedKnots,5*KNOTS_PER_MS);
 assert.deepEqual(vectorReading([0,0]),{speedKnots:0,towardDeg:0});
});
