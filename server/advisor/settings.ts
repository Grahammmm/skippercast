// Text Advisor settings from Worker vars (docs/plans/text-advisor/01-architecture.md
// § "Feature flags, bindings, variables and secrets"). Pure: no I/O, no secrets.
// Every var is optional; a missing or invalid value falls back to its default,
// in the style of lookupSettings (server/boat-lookup.ts), so a typo in a
// repository variable never takes the Worker down or switches a feature on.
import type {Env} from '../env.ts';
import type {AdvisorChannel, AdvisorSettings, VisionProviderName} from './types.ts';

export type AdvisorVars = Pick<Env, 'TEXT_ADVISOR_ENABLED' | 'ADVISOR_REPLIES_ENABLED' | 'ADVISOR_NUMBER' | 'ADVISOR_CHANNEL' |
  'BLUEBUBBLES_PRIVATE_API' | 'ADVISOR_ADMIN_CONTACT_ID' | 'ADVISOR_INBOX_PUBLIC_REPLIES' | 'ADVISOR_MODEL' | 'ADVISOR_VISION_MODEL' |
  'ADVISOR_VISION_PROVIDERS' | 'ADVISOR_DAILY_MESSAGES_PER_CONTACT' | 'ADVISOR_DAILY_LLM_PER_CONTACT' | 'ADVISOR_GLOBAL_DAILY_LLM' |
  'ADVISOR_GLOBAL_DAILY_VISION' | 'ADVISOR_GLOBAL_DAILY_COLD' | 'ADVISOR_PUBLIC_BASE' | 'ADVISOR_REGION_DEFAULT' | 'ADVISOR_AUTO_PUBLISH_AFTER' |
  'ADVISOR_SOCIAL_ENABLED' | 'ADVISOR_INBOX_ENABLED'>;

// Defaults, one place (01 runtime-vars table).
export const ADVISOR_DEFAULTS: Readonly<AdvisorSettings> = Object.freeze({
  enabled: false, repliesEnabled: true, number: null, channel: 'bluebubbles', privateApi: false,
  adminContactId: null, inboxPublicReplies: false, model: 'claude-sonnet-5', visionModel: 'claude-sonnet-5',
  visionProviders: Object.freeze(['hermes', 'claude']) as VisionProviderName[],
  dailyMessagesPerContact: 40, dailyLlmPerContact: 30, globalDailyLlm: 2000, globalDailyVision: 400, globalDailyCold: 50,
  publicBase: 'https://skippercast.com', regionDefault: 'morro-bay', autoPublishAfter: 5,
  socialEnabled: false, inboxEnabled: false,
});

const CHANNELS: readonly AdvisorChannel[] = ['bluebubbles', 'twilio'];
const PROVIDERS: readonly VisionProviderName[] = ['hermes', 'claude'];
const MODEL = /^[\w.:@-]{1,100}$/;                 // same rule as BOAT_AI_MODEL
const E164_US = /^\+1\d{10}$/;
const SLUG = /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/;   // region ids (regions/<id>)
const CONTACT_ID = /^[\w-]{1,64}$/;

const text = (value: unknown): string => typeof value === 'string' ? value.trim() : '';
function flag(value: unknown, fallback: boolean): boolean {
  const v = text(value).toLowerCase();
  return v === 'true' ? true : v === 'false' ? false : fallback;
}
function count(value: unknown, fallback: number): number {
  const raw = text(value), n = Number(raw);
  return raw !== '' && /^\d+$/.test(raw) && Number.isSafeInteger(n) ? n : fallback;
}
const matching = (value: unknown, pattern: RegExp): string | null => { const v = text(value); return pattern.test(v) ? v : null; };

function providers(value: unknown): VisionProviderName[] {
  const names = text(value).toLowerCase().split(',').map(s => s.trim()).filter(Boolean);
  if (!names.length || names.some(n => !(PROVIDERS as readonly string[]).includes(n))) return [...ADVISOR_DEFAULTS.visionProviders];
  return [...new Set(names)] as VisionProviderName[];
}

/** An https URL with no credentials, query or fragment, without its trailing slash; else the default. */
function publicBase(value: unknown): string {
  const raw = text(value);
  if (!raw) return ADVISOR_DEFAULTS.publicBase;
  let url: URL;
  try { url = new URL(raw); } catch { return ADVISOR_DEFAULTS.publicBase; }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || raw.includes('?') || raw.includes('#')) return ADVISOR_DEFAULTS.publicBase;
  return (url.origin + url.pathname).replace(/\/+$/, '');
}

/** Text Advisor settings from Worker vars, every field defaulted (01 runtime-vars table). */
export function advisorSettings(env: AdvisorVars = {}): AdvisorSettings {
  const d = ADVISOR_DEFAULTS, channel = text(env.ADVISOR_CHANNEL).toLowerCase();
  return {
    enabled: flag(env.TEXT_ADVISOR_ENABLED, d.enabled),
    repliesEnabled: flag(env.ADVISOR_REPLIES_ENABLED, d.repliesEnabled),
    number: matching(env.ADVISOR_NUMBER, E164_US) ?? d.number,
    channel: (CHANNELS as readonly string[]).includes(channel) ? channel as AdvisorChannel : d.channel,
    privateApi: flag(env.BLUEBUBBLES_PRIVATE_API, d.privateApi),
    adminContactId: matching(env.ADVISOR_ADMIN_CONTACT_ID, CONTACT_ID) ?? d.adminContactId,
    inboxPublicReplies: flag(env.ADVISOR_INBOX_PUBLIC_REPLIES, d.inboxPublicReplies),
    model: matching(env.ADVISOR_MODEL, MODEL) ?? d.model,
    visionModel: matching(env.ADVISOR_VISION_MODEL, MODEL) ?? d.visionModel,
    visionProviders: providers(env.ADVISOR_VISION_PROVIDERS),
    dailyMessagesPerContact: count(env.ADVISOR_DAILY_MESSAGES_PER_CONTACT, d.dailyMessagesPerContact),
    dailyLlmPerContact: count(env.ADVISOR_DAILY_LLM_PER_CONTACT, d.dailyLlmPerContact),
    globalDailyLlm: count(env.ADVISOR_GLOBAL_DAILY_LLM, d.globalDailyLlm),
    globalDailyVision: count(env.ADVISOR_GLOBAL_DAILY_VISION, d.globalDailyVision),
    globalDailyCold: count(env.ADVISOR_GLOBAL_DAILY_COLD, d.globalDailyCold),
    publicBase: publicBase(env.ADVISOR_PUBLIC_BASE),
    regionDefault: matching(env.ADVISOR_REGION_DEFAULT, SLUG) ?? d.regionDefault,
    autoPublishAfter: count(env.ADVISOR_AUTO_PUBLISH_AFTER, d.autoPublishAfter),
    socialEnabled: flag(env.ADVISOR_SOCIAL_ENABLED, d.socialEnabled),
    inboxEnabled: flag(env.ADVISOR_INBOX_ENABLED, d.inboxEnabled),
  };
}
