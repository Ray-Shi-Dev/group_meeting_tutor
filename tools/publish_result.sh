#!/usr/bin/env bash
# Write one result file into results/ on the ci-results branch.
# Usage: tools/publish_result.sh <source file> <destination name>
# Runs only inside GitHub Actions. The file must not contain tokens, URLs or slide content.
set -euo pipefail

src="$1"
name="$2"
branch="ci-results"
work="$(mktemp -d)"

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

if git fetch --depth=1 origin "$branch" 2>/dev/null; then
  git worktree add --detach "$work" FETCH_HEAD >/dev/null
  git -C "$work" checkout -q -B "$branch"
else
  git worktree add --detach "$work" >/dev/null
  git -C "$work" checkout -q --orphan "$branch"
  git -C "$work" rm -rfq . || true
fi

mkdir -p "$work/results"
cp "$src" "$work/results/$name"
git -C "$work" add results
if git -C "$work" diff --cached --quiet; then
  echo "No change in results; nothing to commit"
else
  git -C "$work" commit -q -m "results: $name @ ${GITHUB_SHA:0:7}"
  for attempt in 1 2 3; do
    if git -C "$work" push -q origin "HEAD:$branch"; then break; fi
    sleep $((attempt * 3))
    git -C "$work" pull -q --rebase origin "$branch"
  done
fi
git worktree remove --force "$work"
