#!/usr/bin/env bash
# Docs integrity check.
#  1. Every relative markdown link in *.md resolves to a file or directory.
#  2. Every file under docs/ is mentioned in README.md (the human index).
# Run from the repo root: bash scripts/check_docs.sh
set -euo pipefail

cd "$(dirname "$0")/.."
fail=0

# 1. Relative links. Skip http(s), mailto, anchors-only, and code blocks are not parsed
#    (links inside fenced code are rare in this repo; keep the check simple).
while IFS= read -r file; do
  dir=$(dirname "$file")
  # Match [text](target) but not images with sizes; strip anchors and titles.
  { grep -oE '\]\(([^)#]+)(#[^)]*)?\)' "$file" || true; } | sed -E 's/^\]\(//; s/\)$//; s/#.*$//; s/ ".*$//' \
    | while IFS= read -r target; do
        [ -z "$target" ] && continue
        case "$target" in
          http://*|https://*|mailto:*) continue ;;
        esac
        if [ ! -e "$dir/$target" ] && [ ! -e "$target" ]; then
          echo "broken link in $file -> $target"
          exit 2
        fi
      done || fail=1
done < <(git ls-files '*.md' 2>/dev/null || find . -name '*.md' -not -path './node_modules/*')

# 2. docs/ index in README.md.
for f in docs/*.md; do
  name=$(basename "$f")
  if ! grep -q "$name" README.md; then
    echo "docs/$name is not listed in README.md"
    fail=1
  fi
done

if [ "$fail" -ne 0 ]; then
  echo "check_docs: FAILED"
  exit 1
fi
echo "check_docs: OK"
