import test from 'node:test';
import assert from 'node:assert/strict';
import {recentDiscussionState,recentDiscussionMarkup} from '../dist/recent-discussions.js';

const now = Date.parse('2026-09-23T16:00:00Z');
const item = (changes={}) => ({region_id:'southern-california',review_status:'candidate',
  url:'https://www.reddit.com/r/SoCalFishing/comments/example',published_at:'2026-09-22T16:00:00Z',
  title:'Yellowtail & kelp',source:'reddit',location_basis:'regional forum only',...changes});
const feed = candidates => ({schema_version:1,generated_at:'2026-09-23T15:00:00Z',
  health:{status:'ok',watchlist_queries:5},checks:{'southern-california/islands':{status:'ok'}},candidates});

test('only fresh regional candidate links appear, without promoting catch claims',()=>{
  const state=recentDiscussionState(feed([item(),item({region_id:'morro-bay'}),item({review_status:'approved'}),
    item({published_at:'2026-08-01T16:00:00Z'}),item({url:'javascript:alert(1)'})]),'southern-california',now);
  assert.equal(state.status,'current');
  assert.equal(state.candidates.length,1);
  assert.match(recentDiscussionMarkup(state),/unreviewed links/);
  assert.match(recentDiscussionMarkup(state),/1\/5 rotating searches/);
  assert.doesNotMatch(recentDiscussionMarkup(state),/verified catch/);
});

test('stale and invalid feeds never display old discussion links',()=>{
  assert.equal(recentDiscussionState({...feed([item()]),generated_at:'2026-09-20T15:00:00Z'},'southern-california',now).candidates.length,0);
  assert.equal(recentDiscussionState({schema_version:2},'southern-california',now).status,'unavailable');
});

test('titles and URLs are escaped before entering the page',()=>{
  const state=recentDiscussionState(feed([item({title:'<img src=x onerror=alert(1)>',url:'https://example.org/?a=1&b=2'})]),'southern-california',now);
  const markup=recentDiscussionMarkup(state);
  assert.doesNotMatch(markup,/<img/);
  assert.match(markup,/&lt;img/);
  assert.match(markup,/a=1&amp;b=2/);
});
