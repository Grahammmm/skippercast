# 0005. Front end: Preact and Vite, with MapLibre and PMTiles for the map

- **Status:** Accepted (2026-10-05, as adopted by [ADR 0009](0009-front-end-rebuild-and-fish-merge.md) with the front-end plan, PR #353; proposed 2026-09-29)
- **Date:** 2026-09-29

## Context

- The app is 75 hand-written, untyped ES modules in `dist/` with no framework, 21 stylesheets and 114 `innerHTML` assignments. Views are closures over the DOM; region changes reload the page. A custom build content-hashes assets.
- The map is Leaflet drawing whole GeoJSON files. PR #10 measured one dense layer both ways: on Southern California survey habitat, MapLibre with PMTiles loaded 58 KB instead of 1.5 MB and stayed responsive where Leaflet took about 50 s per move on a slowed CPU.
- Recent features were built inside this structure: design tokens (#35), the meteogram (#47), the regulations summary (#50), the offline trip pack (#64).
- The Worker moved to strict TypeScript and Hono in #88; the front end is the remaining untyped code. The guide (§3.3, P4-01, P4-05) recommends Vite + TypeScript + Preact with signals, and MapLibre + PMTiles for the map.

## Decision

1. **Vite + TypeScript + Preact + `@preact/signals`**, introduced by wrapping the current modules, not rewriting them. Vite emits the hashed assets; the contract of hashed assets, `no-store` shells and a stable `/sw.js` is kept.
2. **MapLibre GL + PMTiles** replaces Leaflet behind the existing map-initialisation contract. Region layers are published as PMTiles to R2 and served through `/feeds/` ([ADR 0003](0003-r2-system-of-record.md)).
3. URL state (region, target, view, hour) becomes the single source of truth, so changing region no longer reloads the page.

## Consequences

- (+) Typed components end the `innerHTML` and listener-leak class of bugs and enable component tests and Storybook.
- (+) Map cost stays flat as regions grow; the measured 50 s pans go away.
- (–) A migration period with two patterns side by side; every screen needs re-verification on phones.
- (–) A larger toolchain to maintain and patch.
- (–) The pipeline must produce PMTiles for every layer the map draws.

## Alternatives

- **Stay vanilla:** no new dependencies, but the DOM-string pattern does not scale and the audit rated it the main front-end risk.
- **React:** larger runtime for no feature we need; Preact keeps React-compatible tooling.
- **Svelte or Solid:** acceptable technically; smaller ecosystems for Storybook and Testing Library.

## Links

- Guide §3.3, P4-01, P4-05; PRs #10, #35, #47, #50, #64, #88.
