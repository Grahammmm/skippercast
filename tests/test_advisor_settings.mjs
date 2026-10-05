// Text Advisor settings (server/advisor/settings.ts): defaults from the 01
// runtime-vars table, every override, and every invalid value falling back.
import test from 'node:test';
import assert from 'node:assert/strict';
import {advisorSettings, ADVISOR_DEFAULTS} from '../server/advisor/settings.ts';

const DEFAULTS = {
  enabled: false, repliesEnabled: true, number: null, channel: 'bluebubbles', privateApi: false,
  adminContactId: null, inboxPublicReplies: false, model: 'claude-sonnet-5', visionModel: 'claude-sonnet-5',
  visionProviders: ['hermes', 'claude'], dailyMessagesPerContact: 40, dailyLlmPerContact: 30, globalDailyLlm: 2000,
  globalDailyVision: 400, globalDailyCold: 50, publicBase: 'https://skippercast.com', regionDefault: 'morro-bay', autoPublishAfter: 5,
  socialEnabled: false, inboxEnabled: false,
};

test('with no vars every setting is the documented default', () => {
  assert.deepEqual(advisorSettings(), DEFAULTS);
  assert.deepEqual(advisorSettings({}), DEFAULTS);
  assert.deepEqual({...ADVISOR_DEFAULTS, visionProviders: [...ADVISOR_DEFAULTS.visionProviders]}, DEFAULTS);
});

test('every var overrides its setting', () => {
  const settings = advisorSettings({
    TEXT_ADVISOR_ENABLED: 'true', ADVISOR_REPLIES_ENABLED: 'false', ADVISOR_NUMBER: '+18055550123', ADVISOR_CHANNEL: 'twilio',
    BLUEBUBBLES_PRIVATE_API: 'true', ADVISOR_ADMIN_CONTACT_ID: 'c_0123abcd', ADVISOR_INBOX_PUBLIC_REPLIES: 'true',
    ADVISOR_MODEL: 'claude-opus-5-5', ADVISOR_VISION_MODEL: 'claude-haiku-5@2026', ADVISOR_VISION_PROVIDERS: 'claude',
    ADVISOR_DAILY_MESSAGES_PER_CONTACT: '10', ADVISOR_DAILY_LLM_PER_CONTACT: '0', ADVISOR_GLOBAL_DAILY_LLM: '50',
    ADVISOR_GLOBAL_DAILY_VISION: '7', ADVISOR_GLOBAL_DAILY_COLD: '9', ADVISOR_PUBLIC_BASE: 'https://staging.skippercast.com/', ADVISOR_REGION_DEFAULT: 'port-san-luis',
    ADVISOR_AUTO_PUBLISH_AFTER: '3', ADVISOR_SOCIAL_ENABLED: 'true', ADVISOR_INBOX_ENABLED: 'true',
  });
  assert.deepEqual(settings, {
    enabled: true, repliesEnabled: false, number: '+18055550123', channel: 'twilio', privateApi: true,
    adminContactId: 'c_0123abcd', inboxPublicReplies: true, model: 'claude-opus-5-5', visionModel: 'claude-haiku-5@2026',
    visionProviders: ['claude'], dailyMessagesPerContact: 10, dailyLlmPerContact: 0, globalDailyLlm: 50, globalDailyVision: 7, globalDailyCold: 9,
    publicBase: 'https://staging.skippercast.com', regionDefault: 'port-san-luis', autoPublishAfter: 3,
    socialEnabled: true, inboxEnabled: true,
  });
});

test('booleans parse "true"/"false" in any case with surrounding space; anything else is the default', () => {
  for (const value of ['true', 'TRUE', ' True ']) assert.equal(advisorSettings({TEXT_ADVISOR_ENABLED: value}).enabled, true, value);
  for (const value of ['false', 'FALSE', ' False ']) assert.equal(advisorSettings({ADVISOR_REPLIES_ENABLED: value}).repliesEnabled, false, value);
  for (const value of ['', '1', 'yes', 'on', 'truthy', undefined]) {
    assert.equal(advisorSettings({TEXT_ADVISOR_ENABLED: value}).enabled, false, `enabled ${value}`);
    assert.equal(advisorSettings({ADVISOR_REPLIES_ENABLED: value}).repliesEnabled, true, `replies ${value}`);
    assert.equal(advisorSettings({ADVISOR_SOCIAL_ENABLED: value}).socialEnabled, false);
    assert.equal(advisorSettings({ADVISOR_INBOX_ENABLED: value}).inboxEnabled, false);
    assert.equal(advisorSettings({BLUEBUBBLES_PRIVATE_API: value}).privateApi, false);
    assert.equal(advisorSettings({ADVISOR_INBOX_PUBLIC_REPLIES: value}).inboxPublicReplies, false);
  }
});

test('the channel is bluebubbles or twilio only', () => {
  assert.equal(advisorSettings({ADVISOR_CHANNEL: ' Twilio '}).channel, 'twilio');
  assert.equal(advisorSettings({ADVISOR_CHANNEL: 'bluebubbles'}).channel, 'bluebubbles');
  for (const value of ['web', 'sendblue', 'whatsapp', '', 'twilio,bluebubbles']) assert.equal(advisorSettings({ADVISOR_CHANNEL: value}).channel, 'bluebubbles', value);
});

test('vision providers are an ordered, de-duplicated list of hermes and claude', () => {
  assert.deepEqual(advisorSettings({ADVISOR_VISION_PROVIDERS: 'claude,hermes'}).visionProviders, ['claude', 'hermes']);
  assert.deepEqual(advisorSettings({ADVISOR_VISION_PROVIDERS: ' Claude , claude,hermes,,'}).visionProviders, ['claude', 'hermes']);
  assert.deepEqual(advisorSettings({ADVISOR_VISION_PROVIDERS: 'hermes'}).visionProviders, ['hermes']);
  for (const value of ['', ' , ', 'openai', 'claude,openai', 'hermes;claude'])
    assert.deepEqual(advisorSettings({ADVISOR_VISION_PROVIDERS: value}).visionProviders, ['hermes', 'claude'], value);
  // The returned list is a fresh array: changing it never changes the defaults.
  advisorSettings().visionProviders.push('claude');
  assert.deepEqual(advisorSettings().visionProviders, ['hermes', 'claude']);
});

test('model ids follow the BOAT_AI_MODEL rule', () => {
  assert.equal(advisorSettings({ADVISOR_MODEL: ' claude-sonnet-5:beta '}).model, 'claude-sonnet-5:beta');
  for (const value of ['', 'has space', 'x'.repeat(101), 'claude/sonnet', 'model"', '日本']) {
    assert.equal(advisorSettings({ADVISOR_MODEL: value}).model, 'claude-sonnet-5', value);
    assert.equal(advisorSettings({ADVISOR_VISION_MODEL: value}).visionModel, 'claude-sonnet-5', value);
  }
});

test('caps are integers of zero or more; anything else is the default', () => {
  const caps = {ADVISOR_DAILY_MESSAGES_PER_CONTACT: ['dailyMessagesPerContact', 40], ADVISOR_DAILY_LLM_PER_CONTACT: ['dailyLlmPerContact', 30],
    ADVISOR_GLOBAL_DAILY_LLM: ['globalDailyLlm', 2000], ADVISOR_GLOBAL_DAILY_VISION: ['globalDailyVision', 400], ADVISOR_GLOBAL_DAILY_COLD: ['globalDailyCold', 50], ADVISOR_AUTO_PUBLISH_AFTER: ['autoPublishAfter', 5]};
  for (const [name, [key, fallback]] of Object.entries(caps)) {
    assert.equal(advisorSettings({[name]: '0'})[key], 0, `${name} 0`);
    assert.equal(advisorSettings({[name]: ' 12 '})[key], 12, `${name} 12`);
    for (const bad of ['', '-1', '1.5', '1e3', 'abc', '0x10', '99999999999999999999', ' '])
      assert.equal(advisorSettings({[name]: bad})[key], fallback, `${name} ${JSON.stringify(bad)}`);
  }
});

test('the number is E.164 +1 and ten digits, or null', () => {
  assert.equal(advisorSettings({ADVISOR_NUMBER: ' +18055550123 '}).number, '+18055550123');
  for (const bad of ['8055550123', '+1805555012', '+180555501234', '+448055550123', '+1 805 555 0123', '(805) 555-0123', ''])
    assert.equal(advisorSettings({ADVISOR_NUMBER: bad}).number, null, bad);
});

test('the public base is an https URL without credentials, query or fragment', () => {
  assert.equal(advisorSettings({ADVISOR_PUBLIC_BASE: 'https://skippercast.com'}).publicBase, 'https://skippercast.com');
  assert.equal(advisorSettings({ADVISOR_PUBLIC_BASE: 'https://skippercast.example.workers.dev/'}).publicBase, 'https://skippercast.example.workers.dev');
  assert.equal(advisorSettings({ADVISOR_PUBLIC_BASE: 'https://example.com/sc/'}).publicBase, 'https://example.com/sc');
  for (const bad of ['http://skippercast.com', 'skippercast.com', 'https://user:pw@skippercast.com', 'https://skippercast.com/?a=1',
    'https://skippercast.com/#x', 'javascript:alert(1)', 'not a url', ''])
    assert.equal(advisorSettings({ADVISOR_PUBLIC_BASE: bad}).publicBase, 'https://skippercast.com', bad);
});

test('region and admin contact ids are validated', () => {
  for (const bad of ['Morro Bay', '../etc', '-morro', 'morro-', 'MORRO', ''])
    assert.equal(advisorSettings({ADVISOR_REGION_DEFAULT: bad}).regionDefault, 'morro-bay', bad);
  for (const bad of ['has space', 'x'.repeat(65), 'a/b', ''])
    assert.equal(advisorSettings({ADVISOR_ADMIN_CONTACT_ID: bad}).adminContactId, null, bad);
});
