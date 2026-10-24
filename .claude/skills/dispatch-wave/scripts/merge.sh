#!/usr/bin/env bash
# Merge a finished branch into the current branch, gated on the merged tree.
#
#   merge.sh BRANCH -- CHECK_CMD...
#
# Run from the main checkout, on the branch BRANCH forks from, with a clean tree.
# CHECK_CMD runs in a throwaway detached worktree (a sibling of the repo, where tools such as
# mise already trust and cache) holding the merge result: a gate over a whole directory (module
# map, leak matrix) only shows up there, never in a merge-tree dry run.
# Green: merge exactly the commit that was checked, as a fast-forward when BRANCH sits on the
# current branch, else as a merge commit, then remove BRANCH's worktree and BRANCH. Red: nothing changes, the tail of CHECK_CMD's output is
# printed. Never pushes and never force-deletes or rewinds anything.
#
# Exit codes: 0 merged and cleaned up; 1 refused or check red, nothing merged;
#             2 merged, but a cleanup step failed (the message names it).
set -euo pipefail

die() {
  echo "merge.sh: $*" >&2
  exit 1
}

[ $# -ge 3 ] && [ "$2" = "--" ] || die "usage: merge.sh BRANCH -- CHECK_CMD..."
branch=$1
shift 2

git rev-parse --verify --quiet "refs/heads/$branch" >/dev/null || die "no local branch $branch"
current=$(git symbolic-ref --short HEAD) || die "detached HEAD"
[ "$branch" != "$current" ] || die "$branch is the current branch"
[ -z "$(git status --porcelain)" ] || die "working tree is not clean"
[ "$(git rev-parse --path-format=absolute --git-dir)" = "$(git rev-parse --path-format=absolute --git-common-dir)" ] \
  || die "run from the main checkout"

# BRANCH must fork from the current branch, not sit on top of another unmerged branch.
while read -r other; do
  if [ "$other" = "$current" ] || [ "$other" = "$branch" ]; then continue; fi
  if [ -n "$(git rev-list "$current..$other")" ] && git merge-base --is-ancestor "$other" "$branch"; then
    die "$branch sits on top of $other, which is not merged into $current"
  fi
done < <(git for-each-ref --format='%(refname:short)' refs/heads)

sha=$(git rev-parse "refs/heads/$branch")
head=$(git rev-parse HEAD)
repo=$(git rev-parse --show-toplevel)
check=$(mktemp -d "$repo-mergecheck-XXXXXX")
cleanup() {
  git worktree remove --force "$check" 2>/dev/null || true
  rm -rf -- "$check.log" "$check"
}
trap cleanup EXIT

git worktree add --quiet --detach "$check" "$head"
git -C "$check" merge --quiet --no-edit -m "Merge branch '$branch'" "$sha" >"$check.log" 2>&1 \
  || { tail -n 20 "$check.log" >&2; die "merging $branch into $current conflicts"; }

if ! (cd "$check" && "$@") >"$check.log" 2>&1; then
  tail -n 40 "$check.log" >&2
  die "check failed on the merged tree; nothing merged"
fi

[ "$(git rev-parse "refs/heads/$branch")" = "$sha" ] || die "$branch moved during the check; nothing merged"
[ "$(git rev-parse HEAD)" = "$head" ] || die "$current moved during the check; nothing merged"

branch_wt=$(git worktree list --porcelain | awk -v b="refs/heads/$branch" '
  $1 == "worktree" { path = substr($0, 10) }
  $1 == "branch" && $2 == b { print path }')

git merge --quiet --ff --no-edit -m "Merge branch '$branch'" "$sha" || die "merging $branch failed"

cleanup_failed() {
  echo "merge.sh: merged $sha; cleanup failed: $1" >&2
  exit 2
}
if [ -n "$branch_wt" ]; then
  git worktree remove "$branch_wt" || cleanup_failed "git worktree remove $branch_wt"
fi
git branch -d "$branch" || cleanup_failed "git branch -d $branch"
echo "merged $sha"
