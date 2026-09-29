#!/usr/bin/env bash
# Mirror the committed contents of a published feed worktree to Cloudflare R2.
#   scripts/publish_branch_r2.sh <worktree> <conditions|data|forecasts>
# Uses the worktree's HEAD (exactly what GitHub serves), never untracked files.
# Without Cloudflare credentials this does nothing. With credentials, an upload
# failure exits non-zero: the site serves R2 first, so it must not go stale silently.
set -uo pipefail
tree=$1; prefix=$2
if [ -z "${CLOUDFLARE_API_TOKEN:-}" ] || [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
  echo "R2 not configured; skipped $prefix."
  exit 0
fi
if ! git -C "$tree" rev-parse -q --verify HEAD >/dev/null; then
  echo "::warning title=R2 publish::$tree has no commit yet; skipped $prefix"
  exit 0
fi
staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT
git -C "$tree" archive HEAD | tar -x -C "$staging"
if ! python scripts/publish_r2.py "$staging" "$prefix"; then
  echo "::error title=R2 publish::$prefix upload failed; the site keeps serving the previous R2 copy"
  exit 1
fi
