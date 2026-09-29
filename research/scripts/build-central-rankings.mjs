// Publish the existing surveyed atlas's deterministic species habitat ranks.
// These ranks do not establish catch probability or newly surveyed 300-ft spots.
import {readFileSync, writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {speciesFit} from '../../dist/species-fit.js';

const atlasBytes = readFileSync('dist/data/atlas.json');
const atlas = JSON.parse(atlasBytes);
const screen = JSON.parse(readFileSync('dist/data/central-atlas-300-current-closure-screen.json', 'utf8'));
const geometryDigest = createHash('sha256').update(JSON.stringify({
  targets:atlas.targets.map(t=>[t.id,t.latitude,t.longitude]),
  areas:atlas.areas.map(a=>[a.id,a.geometry]),
  drifts:atlas.drifts.map(d=>[d.id,d.geometry]),
})).digest('hex');
if (atlas.fishing_depth_limit_ft !== 200 || atlas.targets.length !== 132 ||
    screen.atlas_source_depth_ceiling_ft !== 200 ||
    screen.input_geometry_sha256 !== geometryDigest ||
    atlas.targets.some(t=>!t.research_only || t.depth_qualified !== false || t.vertical_datum !== 'unverified source datum') ||
    !Number.isFinite(Date.parse(screen.audited_at)) ||
    Date.now() < Date.parse(screen.audited_at) ||
    Date.now() - Date.parse(screen.audited_at) > 36 * 3600_000 ||
    !screen.all_geometry_clear_of_screen_buffers) {
  throw new Error('Atlas or fresh closure screen is outside the reviewed scope');
}
const targets = atlas.targets.map(t => {
  const lingcod = speciesFit(t, 'lingcod');
  const rockfish = speciesFit(t, 'rockfish');
  if (!lingcod || !rockfish || !Number.isFinite(t.latitude) || !Number.isFinite(t.longitude)) {
    throw new Error(`Incomplete species ranking: ${t.id}`);
  }
  return {id:t.id, label:t.label, latitude:t.latitude, longitude:t.longitude,
    center_depth_ft:t.center_depth_ft, neighborhood_depth_ft:t.neighborhood_depth_ft,
    source_id:t.source_id, source_url:t.source_url, survey_year:t.survey_year,
    habitat_score:t.habitat_score, terrain_grade:t.habitat_grade,
    terrain_interpretation_confidence:t.confidence,
    lingcod_fit_rank:lingcod.rank, rockfish_fit_rank:rockfish.rank,
    lingcod_fit_index:lingcod.score, rockfish_fit_index:rockfish.score,
    lingcod_reason:lingcod.reason, rockfish_reason:rockfish.reason};
});
targets.sort((a,b) => a.lingcod_fit_rank-b.lingcod_fit_rank ||
  b.habitat_score-a.habitat_score || a.id.localeCompare(b.id));
const rank_counts = Object.fromEntries(['lingcod','rockfish'].map(species => [species,
  Object.fromEntries([1,2,3].map(rank => [rank,targets.filter(t => t[`${species}_fit_rank`] === rank).length]))]));
const result = {schema_version:1, scope:'central-surveyed-rocky-species-fit',
  source_atlas_edition:atlas.edition, source_depth_ceiling_ft:200,
  chart_depth_qualified:false, source_output_vertical_datum:'unverified',
  boat_planning_depth_ceiling_ft:300, target_count:targets.length,
  closure_audited_at:screen.audited_at, rank_counts,
  rank_thresholds:{strong:{minimum_index:0.9,minimum_rough_cover_fraction:0.7},
    intermediate:{minimum_index:0.7}},
  rank_meaning:{1:'Stronger relative mapped habitat fit',2:'Intermediate relative mapped habitat fit',3:'Lower relative mapped habitat fit'},
  limitations:['These are historical surveyed habitat candidates, not verified catches or fish-presence probabilities.',
    'The original raster output datum and product uncertainty are unresolved. The old nominal 200 ft raster filter is not a chart-depth qualification, and none of these 132 coordinates passes the current fishing-spot gate.',
    'Fresh state/federal GIS screening does not certify current chart, local access, route or season/method clearance.'],
  targets};
writeFileSync('research/receipts/central-rocky-species-rankings.json', JSON.stringify(result,null,2)+'\n');
console.log(rank_counts);
