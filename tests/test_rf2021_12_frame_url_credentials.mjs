// RF2021-12: the nowcoast-frame handler refuses URL userinfo before any fetch. credentials:'omit' does not
// strip user:pass@ from the URL, so the host check alone admitted it. Synthetic URLs and a fake fetch only.
import assert from 'node:assert/strict';
import test from 'node:test';
import {frameProtocol} from '../web/map/frames.ts';

const HOST = 'nowcoast.noaa.gov/wms?x=1', PNG = [137, 80, 78, 71];
const fake = (calls, status = 200) => async (url, init) => {
  calls.push([url, init]);
  return new Response(status === 200 ? new Uint8Array(PNG) : 'busy', {status});
};

test('credentialled_frame_url_is_rejected_without_fetch', async () => {
  const calls = [];
  for (const userinfo of ['user@', 'user:secret@', ':secret@', 'us%40er:p%3Ass@']) {
    await assert.rejects(frameProtocol(fake(calls))({url: `nowcoast-frame://${userinfo}${HOST}`}, new AbortController()), {message: 'frame host'}, userinfo);
  }
  assert.equal(calls.length, 0);
});

test('host_and_protocol_boundary_still_refuse', async () => {
  const calls = [];
  for (const url of ['https://nowcoast.noaa.gov/wms', 'nowcoast-frame://nowcoast.noaa.gov.evil.example/wms', 'nowcoast-frame://xnowcoast.noaa.gov/wms',
    'nowcoast-frame://nowcoast.noaa.gov:8443/wms', 'nowcoast-frame://[bad/wms', 'nowcoast-frame://']) {
    await assert.rejects(frameProtocol(fake(calls))({url}, new AbortController()), {message: 'frame host'}, url);
  }
  const aborted = new AbortController();
  aborted.abort();
  await assert.rejects(frameProtocol(fake(calls))({url: `nowcoast-frame://${HOST}`}, aborted), {name: 'AbortError'});
  assert.equal(calls.length, 0);
});

test('healthy_frame_bytes_and_options_unchanged', async () => {
  const calls = [], ctrl = new AbortController();
  const got = await frameProtocol(fake(calls))({url: `nowcoast-frame://${HOST}`}, ctrl);
  assert.deepEqual([...new Uint8Array(got.data)], PNG);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], `https://${HOST}`);
  assert.equal(calls[0][1].credentials, 'omit');
  assert.equal(calls[0][1].signal, ctrl.signal);
  await assert.rejects(frameProtocol(fake([], 503))({url: `nowcoast-frame://${HOST}`}, new AbortController()), {message: '503'});
});
