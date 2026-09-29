# 0004. Licensing, copyright ownership and contributor terms

- **Status:** Proposed — owner decision required (lawyer recommended)
- **Date:** 2026-09-28

## Context

- [`LICENSE`](../../../LICENSE) (SkipperCast Personal Use License 1.0) §3 forbids use "for a paid, advertising-supported, or sponsored product or service" and any commercial exploitation, and §2 forbids operating the software as a hosted service for others. The planned business is a $10/month hosted app.
- The copyright line is "SkipperCast contributors", not a named person or company. A licensor is not normally bound by its own licence, but with no named holder a buyer's counsel cannot tell who holds title or who could grant a commercial licence.
- History is almost entirely the owner (`Grahammmm`, including Codex work committed as the owner) and Claude (`noreply@anthropic.com`); no outside contributions have been merged. Until now `CONTRIBUTING.md` accepted outside patches with no DCO or CLA.
- Copies already distributed under the personal-use licence (public forks, downloads) keep those terms; a change applies to new versions only.
- No company exists yet (guide §10.1). Whether AI-generated contributions are copyrightable, and by whom, is unsettled; counsel should confirm the owner's position on agent-written code.

## Decision (proposed)

Before charging anyone:

1. **Form the operating entity** (an LLC) and have the owner assign copyright in SkipperCast to it in writing. Replace "SkipperCast contributors" with the entity's name. This is a prerequisite for every option below.
2. **Choose one licence model:**
   - **(a) Keep the personal-use licence**, name the entity as copyright holder, and add "The copyright holder is not bound by this license and may license the Material on other terms." Lowest effort; the code stays public; buyers see an unusual custom licence and competitors can read everything.
   - **(b) Go proprietary:** make the repository private before launch, replace `LICENSE` with "All rights reserved" (keeping `NOTICE.md` for third-party terms). Cleanest title for a sale or investment; loses public visibility and outside contributions.
   - **(c) Source-available with a delayed open licence:** the [Functional Source License](https://fsl.software/) (FSL-1.1, converting to Apache-2.0 or MIT after two years) or the Business Source License 1.1 with a change date. Code stays public and readable, competing commercial use is barred, and the licence is a recognized standard buyers' counsel already knows.

**Recommendation: (b), or (c) with FSL-1.1-ALv2 if public source matters to the owner.** Both give clear title and block a competitor from hosting the same service; (b) is simplest for a sale, (c) keeps the project's openness and credibility. Option (a) is not recommended: the custom licence and "contributors" history remain a diligence question even with the clause added.

3. **Contributor terms (done in this PR):** require a Developer Certificate of Origin sign-off from every non-owner, non-agent contributor, enforced by `.github/workflows/dco.yml`. If the owner picks (b), add a short CLA or copyright assignment for any future outside contributor, since DCO alone certifies origin but does not transfer rights.

`LICENSE` is **not** changed by this ADR. It changes only after the owner decides.

## Consequences

- (+) Title becomes unambiguous; a commercial licence and a sale become possible.
- (+) DCO records the origin of any outside contribution from now on.
- (–) (b) ends public source access; (c) and (b) both change terms for future versions only.
- (–) Entity formation and counsel review cost time and money.

## Alternatives

- Dual licensing (personal-use licence plus paid commercial licence): workable once an entity exists, but keeps the custom licence problem of (a).
- An OSI open-source licence (MIT/Apache-2.0): maximizes openness but lets anyone host a competing paid copy.

## Links

- Engineering audit guide P0-11, §10.1–10.2, finding A3.
- [CONTRIBUTING.md — Developer Certificate of Origin](../../../CONTRIBUTING.md#developer-certificate-of-origin)
- `docs/legal/data-rights-register.md` (third-party data terms are a separate blocker; P0-10).
