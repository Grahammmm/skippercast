import test from 'node:test';
import assert from 'node:assert/strict';
import {speciesFit} from '../dist/species-fit.js';

const target = (relief, rough, area, complexity=1) => ({metrics:{
  relief_210m_m:relief,
  rugose_or_bedrock_fraction_210m:rough,
  rough_habitat_within_250m_ha:area,
  plane_residual_rms_250m_m:complexity,
}});

test('species fit distinguishes structure from extent and uses 1 as strongest', () => {
  const steepSmall=target(15,0.9,1,2);
  const broadLow=target(1,0.9,10,2);
  assert.equal(speciesFit(steepSmall,'lingcod').rank,2);
  assert.equal(speciesFit(broadLow,'lingcod').rank,3);
  assert.equal(speciesFit(broadLow,'rockfish').rank,2);
  assert.equal(speciesFit(target(12,0.95,10,2),'lingcod').rank,1);
  assert.equal(speciesFit(target(12,0.95,10,2),'rockfish').rank,1);
  assert.equal(speciesFit(target(0,0.1,0,0),'rockfish').rank,3);
});

test('withholds species fit for missing metrics or unrelated species', () => {
  assert.equal(speciesFit({},'lingcod'),null);
  assert.equal(speciesFit(target(1,1,1),'albacore'),null);
  assert.equal(speciesFit(target(1,1.2,1),'rockfish'),null);
});
