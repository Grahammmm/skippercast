import test from 'node:test';
import assert from 'node:assert/strict';
import {chooseTiles} from '../packages/coast/src/coast3d/regional.ts';

const T=(x,z,width)=>({x,z,width,lods:[]});
// span 1000 -> radius clamps to 6500 m.
const pick=(tiles,x=100,z=100,span=1000,limit)=>chooseTiles(tiles,x,z,span,limit);

test('containing_tile_is_not_culled_by_its_centre',()=>{
  const big=T(0,0,10000);
  assert.deepEqual(pick([big]),[big]);
});

test('edge_and_corner_overlap_are_geometric',()=>{
  const edge=T(6000,-500,1000),corner=T(-7000,-7000,1000),farEdge=T(6700,-500,1000),farCorner=T(5000,5000,1000);
  // edge: nearest point (6000,100) is 5900 m away; corner: nearest (-6000,-6000) is ~8627 m away.
  assert.deepEqual(pick([edge]),[edge]);
  assert.deepEqual(pick([farEdge]),[]);
  assert.deepEqual(pick([corner]),[]);
  assert.deepEqual(pick([farCorner]),[]);
  const negCorner=T(-6000,-6000,1000);// nearest corner (-5000,-5000) ~7212 m: out
  assert.deepEqual(pick([negCorner]),[]);
  const negIn=T(-5000,-5000,1000);// nearest corner (-4000,-4000) ~5798 m: in
  assert.deepEqual(pick([negIn]),[negIn]);
});

test('radius_tangency_remains_excluded',()=>{
  const tangent=T(6600,0,1000),inward=T(6599,0,1000);
  assert.deepEqual(pick([tangent]),[]);
  assert.deepEqual(pick([inward]),[inward]);
});

test('limits_sort_and_identity_are_preserved',()=>{
  const tiles=[T(3000,0,1024),T(0,0,1024),T(1000,0,1024),T(0,0,1024)];
  const copy=[...tiles];
  const out=pick(tiles);
  assert.ok(tiles.every((t,i)=>t===copy[i]),'input not reordered');
  assert.equal(out.length,4);
  assert.ok(out[0]===tiles[1]&&out[1]===tiles[3],'nearest centres first, stable ties');
  assert.ok(out[2]===tiles[2]&&out[3]===tiles[0]);
  const capped=pick(tiles,100,100,1000,2);
  assert.ok(capped.length===2&&capped[0]===tiles[1]&&capped[1]===tiles[3]);
  const many=Array.from({length:150},(_,i)=>T(i*10,0,1024));
  assert.equal(pick(many).length,100);
});
