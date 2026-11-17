import test from 'node:test';
import assert from 'node:assert/strict';
import {reefBindingMatches} from '../packages/coast/src/coast3d/regional.ts';

const NOW=Date.parse('2026-01-01T00:00:00Z');
const FUTURE='2026-06-01T00:00:00Z';
const row=(id,a,e)=>({regionId:id,archiveSha256:a,exportSha256:e});
const A=row('synthetic-a','a','b'),B=row('synthetic-b','c','d'),C=row('synthetic-c','e','f');
const ctx=(regions,expiresAt=FUTURE)=>({regions,expiresAt});
const man=regions=>({regions});

test('reef_context_duplicate_cannot_replace_missing_region',()=>{
  assert.equal(reefBindingMatches(ctx([A,A]),man([A,B]),NOW),false);
  assert.equal(reefBindingMatches(ctx([A,A,B]),man([A,B,C]),NOW),false);
  assert.equal(reefBindingMatches(ctx([B,A,A]),man([A,B,C]),NOW),false);
});

test('reef_manifest_and_context_ids_must_each_be_unique',()=>{
  assert.equal(reefBindingMatches(ctx([A,B]),man([A,A]),NOW),false);
  assert.equal(reefBindingMatches(ctx([A,A]),man([A,A]),NOW),false);
  const A2=row('synthetic-a','x','y');
  assert.equal(reefBindingMatches(ctx([A,A2]),man([A,A2]),NOW),false);
  assert.equal(reefBindingMatches(ctx([A,B]),man([A,A2]),NOW),false);
});

test('reef_unique_sets_match_in_any_order_without_mutation',()=>{
  const c=Object.freeze([Object.freeze({...A}),Object.freeze({...B})]);
  const m=Object.freeze([Object.freeze({...B}),Object.freeze({...A})]);
  const before=JSON.stringify([c,m]);
  assert.equal(reefBindingMatches(ctx(c),man(m),NOW),true);
  assert.equal(reefBindingMatches(ctx([A,B]),man([A,B]),NOW),true);
  assert.equal(JSON.stringify([c,m]),before);
});

test('reef_existing_identity_and_expiry_controls',()=>{
  assert.equal(reefBindingMatches(ctx([A]),man([A]),NOW),true);
  assert.equal(reefBindingMatches(ctx([]),man([]),NOW),true);
  assert.equal(reefBindingMatches(ctx([A]),man([{...A,archiveSha256:'z'}]),NOW),false);
  assert.equal(reefBindingMatches(ctx([A]),man([{...A,exportSha256:'z'}]),NOW),false);
  assert.equal(reefBindingMatches(ctx([A]),man([A,B]),NOW),false);
  assert.equal(reefBindingMatches(ctx([A,B]),man([A]),NOW),false);
  assert.equal(reefBindingMatches(ctx([A],FUTURE),man([A]),Date.parse(FUTURE)),false);
  assert.equal(reefBindingMatches(ctx([A],FUTURE),man([A]),Date.parse(FUTURE)+1),false);
});
