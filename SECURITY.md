# Security policy

## Reporting a vulnerability

Please report security problems **privately** through GitHub's private vulnerability reporting:
open the repository's **Security** tab and choose **Report a vulnerability**
(<https://github.com/Grahammmm/skippercast/security/advisories/new>).

Do not open a public issue, pull request or discussion for a vulnerability, and do not include other people's personal data in a report.

Useful details: the affected URL, route or file; steps to reproduce; the impact you observed; and whether it is already public.

## What to expect

- We aim to acknowledge a report within 5 working days and to agree a disclosure date with you once the problem is understood.
- Fixes ship through the normal pull-request process; the advisory is published after the fix is deployed.
- SkipperCast is maintained by one person with AI agents, so there is no bug bounty.

## Scope

In scope: the SkipperCast web app and Worker (`server/`), its public API routes (`/api/*`, `/feeds/*`), the build and deployment workflows, and the data pipeline in this repository.

Out of scope: third-party data providers and services SkipperCast links to or reads from (report those to the provider), denial-of-service tests against production, and social engineering.

## Supported versions

Only the current deployment built from `main` is supported.
