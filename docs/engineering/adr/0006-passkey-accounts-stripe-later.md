# 0006. SkipperCast accounts with passkeys now; Stripe billing later

- **Status:** Accepted for passkey accounts (PR #62). Proposed for billing — owner decision required.
- **Date:** 2026-09-29

## Context

- Private features (trip alerts, push, feedback, the AI boat lookup) need an owner. Identity used to come from ChatGPT Sites headers, which anyone could forge on our own Worker. PR #24 failed closed and PR #58 removed Sites, so private routes answered 401 until SkipperCast had accounts.
- The guide (§3.2, P3-02) proposed Better Auth on D1 with email magic links, Sign in with Apple and Google. Each needs owner-held keys or OAuth apps.
- A paid tier needs billing and entitlements (§3.2, P3-03), which need a legal entity and a Stripe account ([ADR 0004](0004-licensing.md), guide §10).

## Decision

**Accounts (accepted, PR #62):** SkipperCast's own accounts, with WebAuthn passkeys as the only credential: no email, password or OAuth.

- D1 tables `users`, `passkeys`, `sessions` (token SHA-256 only) and `auth_challenges` (single use, 5 minutes).
- Cookie `__Host-sc_session` (`HttpOnly`, `Secure`, `SameSite=Lax`, 30 days); Origin check on mutations; 20 auth requests a minute per IP.
- Identity resolves only when `IDENTITY_PROVIDER=skippercast`; any other value fails closed.
- Users can add and remove passkeys (never the last), export their data and delete the account.

**Billing (proposed):** Stripe Checkout and Customer Portal, a verified idempotent webhook, and a plan check on premium routes, keyed to `users.id`. Deferred until the entity, licence and data-rights blockers are resolved; nothing is built.

## Consequences

- (+) No third-party identity provider, email service or stored password.
- (+) Phishing-resistant sign-in and very little personal data to protect.
- (–) No email means no recovery if every passkey is lost; a second passkey is the only backup.
- (–) Passkeys are unfamiliar to some users; older devices may lack support.
- (–) Billing will bring a customer email from Stripe checkout that the account must link.

## Alternatives

- **Better Auth with magic link, Apple and Google** (the guide's plan): more familiar, but blocked on owner-held keys. Can be added later on the same `users` table.
- **Cloudflare Access:** a workforce product with per-seat pricing and no self-serve sign-up.
- **Keep ChatGPT Sites identity:** ties users to another company's platform; abandoned in PR #58.

## Links

- PRs #24, #58, #62; guide P0-01, P3-02, P3-03, P3-07, finding A1; [API reference](../api-reference.md), [threat model](../../legal/threat-model.md).
