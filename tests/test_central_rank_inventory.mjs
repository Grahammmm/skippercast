import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {speciesFit} from '../dist/species-fit.js';

test('published rocky fit inventory matches every surveyed target and remains distinct from evidence confidence', () => {
  const atlas=JSON.parse(readFileSync('dist/data/atlas.json'));
  const inventory=JSON.parse(readFileSync('dist/data/central-rocky-species-rankings.json'));
  assert.equal(inventory.target_count,atlas.targets.length);
  assert.equal(inventory.source_depth_ceiling_ft,200);
  assert.equal(inventory.boat_planning_depth_ceiling_ft,300);
  const rows=new Map(inventory.targets.map(row=>[row.id,row]));
  assert.equal(rows.size,atlas.targets.length);
  for(const target of atlas.targets) {
    const row=rows.get(target.id);
    assert.ok(row,`missing ${target.id}`);
    assert.equal(row.terrain_interpretation_confidence,target.confidence);
    for(const species of ['lingcod','rockfish']) {
      const fit=speciesFit(target,species);
      assert.equal(row[`${species}_fit_rank`],fit.rank);
      assert.equal(row[`${species}_fit_index`],fit.score);
    }
  }
  for(const species of ['lingcod','rockfish']) {
    const count=inventory.rank_counts[species];
    assert.equal(Object.values(count).reduce((sum,n)=>sum+n,0),atlas.targets.length);
    assert.ok(count[1]<atlas.targets.length/2,'rank 1 must remain selective');
  }
});
