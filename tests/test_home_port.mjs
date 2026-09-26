import assert from 'node:assert/strict';
import test from 'node:test';
import {hasAreaLink, portURL, closestPort} from '../dist/home-port.js';

const morro={id:'morro-bay',region:'morro-bay',view:[35.36,-120.94,10],match:[35.3667,-120.868]};
const sanDiego={id:'san-diego',region:'southern-california',view:[32.84,-117.45,10],match:[32.72,-117.22]};

test('only a bare visit opens port choice; shared region and view links stay authoritative',()=>{
  assert.equal(hasAreaLink('https://skippercast.com/'),false);
  assert.equal(hasAreaLink('https://skippercast.com/?utm_source=friend'),false);
  assert.equal(hasAreaLink('https://skippercast.com/?region=southern-california#map'),true);
  assert.equal(hasAreaLink('https://skippercast.com/?coast=central'),true);
  assert.equal(hasAreaLink('https://skippercast.com/?view=35.2,-120.9,10'),true);
  assert.equal(hasAreaLink('https://skippercast.com/#forecast'),true);
});

test('port navigation chooses its forecast map while retaining unrelated link parameters',()=>{
  const url=new URL(portURL('https://skippercast.com/?utm_source=friend&coast=central&target=reef#forecast',sanDiego));
  assert.equal(url.searchParams.get('region'),'southern-california');
  assert.equal(url.searchParams.get('view'),'32.84000,-117.45000,10');
  assert.equal(url.searchParams.get('target'),null);
  assert.equal(url.searchParams.get('utm_source'),'friend');
  assert.equal(url.hash,'#map');
});

test('nearest-port suggestion stays local and refuses a distant match',()=>{
  assert.equal(closestPort([morro,sanDiego],35.36,-120.88)?.id,'morro-bay');
  assert.equal(closestPort([morro,sanDiego],37,-119),null);
  assert.equal(closestPort([morro],NaN,-120.9),null);
});
