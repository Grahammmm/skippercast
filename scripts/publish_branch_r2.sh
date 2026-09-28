#!/usr/bin/env bash
# Mirror the committed contents of a published feed worktree to Cloudflare R2.
#   scripts/publish_branch_r2.sh <worktree> <conditions|data|forecasts>
# Uses the worktree's HEAD (exactly what GitHub serves), never untracked files.
# Without Cloudflare credentials this does nothing; failures only warn.
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
python scripts/publish_r2.py "$staging" "$prefix" || echo "::warning title=R2 publish::$prefix upload failed; GitHub copy is current"
