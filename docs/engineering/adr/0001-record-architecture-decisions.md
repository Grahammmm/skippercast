# 0001. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

SkipperCast is built by one owner and two AI agents working in parallel, at high speed. Decisions that shape the product (data providers, hosting, licensing, framework choices) have so far lived in PR descriptions, dated audit logs and chat, where they are hard to find and easy to contradict. A buyer, a new contributor or a future agent needs to know *why* the system is the way it is, not only *what* it is.

## Decision

Record each significant, hard-to-reverse decision as an Architecture Decision Record (ADR) in `docs/engineering/adr/NNNN-short-title.md`, numbered in order and never renumbered. Use the template below and aim for about 400 words; an ADR that lays out options for an owner decision may run longer.

```markdown
# NNNN. Title in the imperative

- **Status:** Proposed | Accepted | Superseded by NNNN | Rejected
- **Date:** YYYY-MM-DD

## Context
The forces at play, facts and constraints. Link evidence.

## Decision
What we will do, stated plainly.

## Consequences
- (+) What gets easier or better.
- (–) What gets harder, riskier or more expensive.

## Alternatives
Options considered and why they were not chosen.

## Links
Issues, PRs, docs, guide sections.
```

Rules:

- An ADR that needs the owner's decision stays **Proposed** until the owner accepts or rejects it in the PR or an issue; agents never mark such an ADR Accepted themselves.
- Accepted ADRs are not edited to change the decision; write a new ADR that supersedes it and update the old one's status line.
- A PR that implements or depends on a decision links its ADR.

## Consequences

- (+) Decisions become discoverable and reviewable; agents can check an ADR before changing a load-bearing choice.
- (+) Due diligence (licensing, data rights, hosting) has a single trail.
- (–) Small overhead per significant decision.

## Alternatives

- Keep decisions in PR descriptions only: not discoverable, and PRs mix decisions with implementation detail.
- A wiki: lives outside the repository and review process.

## Links

- Engineering audit guide §8 (documentation architecture) and P5-03.
- [Index of ADRs](README.md).
