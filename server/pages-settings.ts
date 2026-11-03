// Public port and species pages are opt-in independently of Text Advisor.
export function publicPagesSettings(env: {PUBLIC_PAGES_ENABLED?: string}): {enabled: boolean} {
  return {enabled: env.PUBLIC_PAGES_ENABLED?.trim().toLowerCase() === 'true'};
}
