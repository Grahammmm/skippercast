#!/usr/bin/env bash
# Mirror the committed contents of a published feed worktree to Cloudflare R2.
#   scripts/publish_branch_r2.sh <worktree> <conditions|data|forecasts>
# Archives the worktree's committed HEAD, never untracked files. A data mirror
# checks that this exact commit is still on origin before promoting it in R2.
# Without Cloudflare credentials this does nothing. With credentials, an upload
# failure exits non-zero: the site serves R2 first, so it must not go stale silently.
set -euo pipefail
tree=$1; prefix=$2
if [ -z "${CLOUDFLARE_API_TOKEN:-}" ] || [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
  echo "R2 not configured; skipped $prefix."
  exit 0
fi
if ! commit=$(git -C "$tree" rev-parse -q --verify HEAD); then
  echo "::warning title=R2 publish::$tree has no commit yet; skipped $prefix"
  exit 0
fi
staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT
archive="$staging/feed.tar"
mkdir "$staging/tree"
if ! git -C "$tree" archive --format=tar --output="$archive" "$commit"; then
  echo "::error title=R2 publish::$prefix archive creation failed; upload skipped" >&2
  exit 1
fi
if ! tar -xf "$archive" -C "$staging/tree"; then
  echo "::error title=R2 publish::$prefix archive extraction failed; upload skipped" >&2
  exit 1
fi
options=(--branch-archive "$archive")
if [ "$prefix" = data ]; then
  options+=(--branch-worktree "$tree")
fi
if ! python scripts/publish_r2.py "$staging/tree" "$prefix" "${options[@]}"; then
  echo "::error title=R2 publish::$prefix upload failed; no partial snapshot is committed (a lost final acknowledgment may have committed a complete release)"
  exit 1
fi
