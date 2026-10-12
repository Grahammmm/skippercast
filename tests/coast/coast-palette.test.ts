// FE-76 (design § 3A.4): the renderer reads its colours from one palette, and
// series SVG carries colours in style properties so var() resolves.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DEFAULT_COAST_PALETTE} from '../../packages/coast/src/palette.ts';
import {chart} from '../../packages/coast/src/charts/series.ts';

const HEX=/#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])/g;
// The shader's former literals (linear working-space values) as sRGB hex: three converts them back.
const V1_SHADER={depthShallow:[.32,.69,.63],depthChannel:[.035,.28,.39],depthDeep:[.015,.095,.19],landLow:[.51,.56,.38],landHigh:[.72,.71,.53],waterTint:[.17,.57,.66],contour:[.05,.22,.28]} as const;
test('DEFAULT_COAST_PALETTE pins the viewer\'s v1 colours, the shader ramp and the 3D sky',()=>{
 assert.deepEqual({...DEFAULT_COAST_PALETTE},{ground:'#dce8e7',sky:'#effbff',groundLight:'#4b655d',sun:'#fff2d4',surface:'#ffffff',
  gradeA:'#f8d69a',gradeB:'#afd7ba',gradeOther:'#abcad8',habitatArea:'#69e6c3',current:'#fcfaf0',
  skyTop:'#8fb3bd',depthShallow:'#99d8d0',depthMid:'#4b9baf',depthChannel:'#3590a8',depthDeep:'#215779',
  landLow:'#bdc5a6',landHigh:'#dddbc0',waterTint:'#73c7d4',contour:'#3f8190'});
 assert.equal(new Set(Object.values(DEFAULT_COAST_PALETTE)).size,19);
 const linear=(hex:string)=>[1,3,5].map(i=>{const c=parseInt(hex.slice(i,i+2),16)/255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4;});
 for(const [role,values] of Object.entries(V1_SHADER))linear(DEFAULT_COAST_PALETTE[role as keyof typeof V1_SHADER]).forEach((v,i)=>assert.ok(Math.abs(v-values[i]!)<.006,`${role} ${v} vs ${values[i]}`));
 assert.ok(Object.isFrozen(DEFAULT_COAST_PALETTE));
});
test('CoastViewer has no colour literal of its own',()=>{
 const source=readFileSync(new URL('../../packages/coast/src/coast3d/viewer.ts',import.meta.url),'utf8');
 assert.deepEqual(source.match(HEX),null);
 assert.match(source,/import \{DEFAULT_COAST_PALETTE as palette\} from '\.\.\/palette\.ts';/);
});
test('series SVG keeps v1 colours as var(--coast-…) fallbacks in style, never in attributes',()=>{
 const points=[{at:'2026-10-06T12:00:00Z',value:1},{at:'2026-10-06T15:00:00Z',value:2}];
 const svg=chart([{label:'Tide',unit:'ft',color:'var(--coast-amber,#eabd76)',points}],'2026-10-06T10:00:00Z','2026-10-06T18:00:00Z','2026-10-06T13:00:00Z','America/Los_Angeles',
  {sunrise:'2026-10-06T11:00:00Z',sunset:'2026-10-06T17:00:00Z',windows:[{start:'2026-10-06T12:00:00Z',end:'2026-10-06T14:00:00Z'}]});
 assert.doesNotMatch(svg,/\s(?:fill|stroke)="(?!none")/);
 const fallbacks=[...svg.matchAll(/style="(fill|stroke):var\(--coast-([\w-]+),(#[0-9a-f]+)\)"/g)].map(m=>`${m[1]} ${m[2]} ${m[3]}`);
 assert.deepEqual([...new Set(fallbacks)].sort(),['fill amber #eabd76','fill mint #58e8b8','fill night #030d17','fill text #e3f7ff',
  'stroke amber #eabd76','stroke muted #86abc2','stroke text #e3f7ff']);
});
