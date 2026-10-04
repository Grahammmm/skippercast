// Shared types of the Text Advisor (docs/plans/text-advisor/01-architecture.md).
// TA-F1 needs only the settings shape and the queue message; later tasks add
// InboundMessage, OutboundMessage, Action, EngineResult, Contact and the rest
// here, next to these, so every advisor module imports its types from one file.

export type AdvisorChannel = 'bluebubbles' | 'twilio';
export type VisionProviderName = 'hermes' | 'claude';

/** Every runtime var in 01 § "Feature flags", parsed and defaulted by advisorSettings(). */
export interface AdvisorSettings {
  enabled: boolean;                 // TEXT_ADVISOR_ENABLED: hard switch, every advisor route 404s when off
  repliesEnabled: boolean;          // ADVISOR_REPLIES_ENABLED: soft switch, inbound stored but nothing sent
  number: string | null;            // ADVISOR_NUMBER: the owned number, E.164 (+1 and ten digits)
  channel: AdvisorChannel;          // ADVISOR_CHANNEL: adapter for outbound texts
  privateApi: boolean;              // BLUEBUBBLES_PRIVATE_API: typing indicators and read receipts
  adminContactId: string | null;    // ADVISOR_ADMIN_CONTACT_ID: owner's contact for the text admin fallback
  inboxPublicReplies: boolean;      // ADVISOR_INBOX_PUBLIC_REPLIES: public replies to non-keyword IG comments
  model: string;                    // ADVISOR_MODEL: text model id
  visionModel: string;              // ADVISOR_VISION_MODEL: Claude vision fallback model id
  visionProviders: VisionProviderName[]; // ADVISOR_VISION_PROVIDERS: ordered provider chain, never empty
  dailyMessagesPerContact: number;  // ADVISOR_DAILY_MESSAGES_PER_CONTACT
  dailyLlmPerContact: number;       // ADVISOR_DAILY_LLM_PER_CONTACT
  globalDailyLlm: number;           // ADVISOR_GLOBAL_DAILY_LLM
  globalDailyVision: number;        // ADVISOR_GLOBAL_DAILY_VISION
  publicBase: string;               // ADVISOR_PUBLIC_BASE: https origin (and optional path), no trailing slash
  regionDefault: string;            // ADVISOR_REGION_DEFAULT: region id for contacts with no home port
  autoPublishAfter: number;         // ADVISOR_AUTO_PUBLISH_AFTER: clean reports before auto-publish is offered
  socialEnabled: boolean;           // ADVISOR_SOCIAL_ENABLED: publishing to Meta
  inboxEnabled: boolean;            // ADVISOR_INBOX_ENABLED: IG DM and comment handling
}

/** The one message shape on ADVISOR_QUEUE: the stored inbound message to process. */
export interface AdvisorMessage {message_id: string}
