# Release process

SkipperCast uses [semantic versions](https://semver.org/) (`MAJOR.MINOR.PATCH`) and git tags `vX.Y.Z`. `main` is always deployable; a release names a tested point on `main` and records what changed for users. Rules for branches and PRs are in [AGENTS.md](../../AGENTS.md).

## When to release

Cut a release after merging a user-facing change (AGENTS.md → Releases), or at least weekly while changes are landing. Patch: fixes only. Minor: new features or data coverage. Major: breaking changes to feeds, exports or accounts.

## Keeping the changelog

Every PR with a user-facing or operational change adds one line under `## Unreleased` in [CHANGELOG.md](../../CHANGELOG.md):

- **User-facing lines** go directly under `## Unreleased`: one line per change, written for someone using the app.
- **Pipeline, CI, research and infrastructure lines** go under `### Internal`.

## Steps

1. **Bump the version** in one PR titled `Release vX.Y.Z`, from a fresh `main`:
   - `package.json` → `"version"`;
   - `pyproject.toml` → `version`;
   - `src/skippercast/__init__.py` → `__version__`;
   - `server/worker.js` → the `version` reported by `/api/health`.

   `tests/test_versions.py` fails if the first three and the newest CHANGELOG heading disagree.
2. **Cut the changelog** in the same PR: rename `## Unreleased` to `## X.Y.Z — YYYY-MM-DD`, keep its `### Internal` subsection, and add a new empty `## Unreleased` above it. Check the notes with `python3 scripts/changelog_section.py vX.Y.Z`.
3. **Merge** after CI passes.
4. **Tag the merge commit** (annotated) and push the tag:

   ```bash
   git fetch origin main
   git tag -a vX.Y.Z origin/main -m "SkipperCast X.Y.Z"
   git push origin vX.Y.Z
   ```

5. **GitHub Release** — [`.github/workflows/release.yml`](../../.github/workflows/release.yml) runs on the tag push, checks that the tagged `package.json` matches the tag, and creates the release with the CHANGELOG section as notes. For a tag on a commit older than the workflow, run **Actions → Release → Run workflow** with the tag name.
6. **Deploy** — merges to `main` deploy through `Deploy to Cloudflare` (see [Cloudflare](../cloudflare.md)); skippercast.com on ChatGPT Sites is published from the same commit (see [production operations](../production-operations.md)). Confirm the deployed commit is the tagged one.
7. **Post-deploy checks**:
   - `/api/health` reports the new `version` and a new `build`;
   - the map, Forecast and Guide load on a phone-sized browser; `/terms.html`, `/privacy.html`, `/licenses.html`, `/sources.html` load;
   - `/feeds/conditions/latest.json` is fresh (the feed-freshness workflow is green);
   - no new errors in Worker logs.

## Rolling back

Redeploy the previous tag: run the deploy workflow on `vX.Y.(Z-1)` (or check it out and deploy), then open a PR that reverts the faulty change on `main`. Do not delete or move a published tag; fix forward with a new patch release.

## Tagging history

Releases 0.1.0–0.3.0 were made before tagging started. `v0.3.0` belongs on the commit that bumped `package.json` to 0.3.0 (`31d453e`, 2026-09-21); `pyproject.toml` was aligned to 0.3.0 later in `9d57831`.
