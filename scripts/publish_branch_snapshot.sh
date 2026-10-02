#!/usr/bin/env bash
# Publish a feed directory to its git branch as ONE parentless commit, so the
# `conditions`, `data` and `forecasts` branches never accumulate history.
#
#   scripts/publish_branch_snapshot.sh --load <branch> <dir>
#       Make <dir> hold exactly what <branch> on origin holds now: a detached
#       worktree of the published commit, or an empty repository when the branch
#       does not exist yet. Re-running it after someone else published re-bases
#       <dir> on their commit (and discards local changes); it is a no-op when
#       <dir> already holds the published commit.
#
#   scripts/publish_branch_snapshot.sh <branch> <dir> <message>
#       Commit everything in <dir> (git add -A: the directory IS the snapshot)
#       as a commit with no parent and force-push it with a lease on the commit
#       <dir> was loaded from. If another job published in between, the push is
#       refused and this exits 1; nothing is overwritten. Unchanged content is
#       not re-published. Afterwards <dir>'s HEAD is the published commit, which
#       is what publish_branch_r2.sh mirrors to R2.
#
# Run from the repository root; <dir> pushes to the root checkout's origin.
set -euo pipefail

bot_identity() {
  export GIT_AUTHOR_NAME='github-actions[bot]' GIT_AUTHOR_EMAIL='41898282+github-actions[bot]@users.noreply.github.com'
  export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
}

own_repo() {  # <dir> must be its own repository or worktree, never a folder inside this checkout
  [ "$(git -C "$1" rev-parse --show-toplevel 2>/dev/null)" = "$(cd "$1" && pwd -P)" ] || {
    echo "::error title=Feed branch::$1 is not a published-feed repository" >&2; return 1; }
}

remote_head() {  # sha of origin's <branch>, or empty when it does not exist
  git ls-remote origin "refs/heads/$1" | cut -f1
}

load() {
  local branch=$1 dir=$2 remote current
  remote=$(remote_head "$branch")
  if [ -d "$dir" ]; then
    own_repo "$dir"
    current=$(git -C "$dir" rev-parse -q --verify HEAD || true)
    [ "$current" = "$remote" ] && return 0
    [ -n "$remote" ] || { echo "::error title=Feed branch::$branch vanished from origin; $dir still holds ${current:0:12}" >&2; return 1; }
    echo "::warning title=Feed branch::$branch moved on origin (${current:0:12} -> ${remote:0:12}); reloading $dir"
    git -C "$dir" fetch -q --depth=1 origin "refs/heads/$branch"
    git -C "$dir" checkout -q -f --detach FETCH_HEAD
    git -C "$dir" clean -q -fdx
    return 0
  fi
  if [ -n "$remote" ]; then
    git fetch -q --depth=1 origin "refs/heads/$branch"
    # Runner cleanup may remove the directory but leave its Git registration.
    # One --force reclaims only this missing path; locked worktrees still fail.
    # Do not prune unrelated worktrees used by other jobs or agent chats.
    git worktree add -q --detach --force "$dir" FETCH_HEAD
  else
    mkdir -p "$dir"
    git -C "$dir" init -q -b "$branch"
    git -C "$dir" remote add origin "$(git remote get-url origin)"
    local header
    header=$(git config --get http.https://github.com/.extraheader || true)
    if [ -n "$header" ]; then git -C "$dir" config http.https://github.com/.extraheader "$header"; fi
  fi
}

publish() {
  local branch=$1 dir=$2 message=$3 base tree commit
  own_repo "$dir"
  base=$(git -C "$dir" rev-parse -q --verify HEAD || true)
  git -C "$dir" add -A
  tree=$(git -C "$dir" write-tree)
  if [ -n "$base" ] && [ "$tree" = "$(git -C "$dir" rev-parse "$base^{tree}")" ]; then
    echo "$branch unchanged; not re-published."
    return 0
  fi
  bot_identity
  commit=$(git -C "$dir" commit-tree "$tree" -m "$message")
  # The lease names the commit this snapshot was built on (empty: the branch must
  # not exist yet), so a concurrent publish is refused instead of replaced.
  if ! git -C "$dir" push -q --force-with-lease="refs/heads/$branch:$base" origin "$commit:refs/heads/$branch"; then
    echo "::error title=Feed branch::$branch changed on origin since ${base:0:12}; not overwritten" >&2
    return 1
  fi
  git -C "$dir" reset -q --soft "$commit"
  echo "Published $branch as single commit ${commit:0:12}."
}

if [ "${1:-}" = "--load" ]; then
  [ $# -eq 3 ] || { echo "usage: $0 --load <branch> <dir>" >&2; exit 2; }
  load "$2" "$3"
else
  [ $# -eq 3 ] || { echo "usage: $0 <branch> <dir> <message>" >&2; exit 2; }
  publish "$1" "$2" "$3"
fi
