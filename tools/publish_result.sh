#!/usr/bin/env bash
# 把一個結果檔寫進 ci-results 分支的 results/ 目錄。
# 用法：tools/publish_result.sh <來源檔> <目的檔名>
# 只在 GitHub Actions 裡執行；結果檔必須不含 token、網址或簡報內容。
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
  echo "結果沒有變化，不提交"
else
  git -C "$work" commit -q -m "results: $name @ ${GITHUB_SHA:0:7}"
  for attempt in 1 2 3; do
    if git -C "$work" push -q origin "HEAD:$branch"; then break; fi
    sleep $((attempt * 3))
    git -C "$work" pull -q --rebase origin "$branch"
  done
fi
git worktree remove --force "$work"
