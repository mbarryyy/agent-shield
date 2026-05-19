#!/usr/bin/env bash
# Agent Shield — NO-AI-ATTRIBUTION lint (W0 standing constraint #1).
#
# Phase 1 — commit/author scan: fails if ANY commit in the reviewed range, OR
# its author/committer identity, carries AI attribution:
#   - "Co-Authored-By: Claude"        (case-insensitive)
#   - "Generated with Claude"         (case-insensitive)
#   - the 🤖 robot emoji
#   - author/committer name or email containing "claude" or "anthropic"
#
# Phase 2 — tracked-file CONTENT scan: fails if any tracked file (code, docs,
# CHANGELOG, NOTICE, …) contains AI-attribution PHRASING. Bounded so it never
# matches legitimate model-id / dependency / vendor strings (claude-sonnet,
# anthropic>=, ANTHROPIC_API_KEY, claudecode|letta, "Claude Code/Letta",
# "Claude worker", claude-3-haiku). The two pathspec exclusions are the rule's
# OWN definitional text (this script; the PR template enumerating the forbidden
# patterns by design) — not a loophole.
#
# Range resolution (works in PR CI, push CI, and locally):
#   PR_BASE_SHA..PR_HEAD_SHA  >  PUSH_BEFORE..PUSH_AFTER  >  all of HEAD
set -euo pipefail

ZERO="0000000000000000000000000000000000000000"

range=""
if [[ -n "${PR_BASE_SHA:-}" && -n "${PR_HEAD_SHA:-}" ]]; then
  range="${PR_BASE_SHA}..${PR_HEAD_SHA}"
elif [[ -n "${PUSH_BEFORE:-}" && "${PUSH_BEFORE:-}" != "$ZERO" && -n "${PUSH_AFTER:-}" ]]; then
  range="${PUSH_BEFORE}..${PUSH_AFTER}"
fi

# Portable (bash 3.2 / macOS) — no `mapfile`.
commits=()
if [[ -n "$range" ]]; then
  src="$(git rev-list "$range" 2>/dev/null || true)"
else
  src="$(git rev-list HEAD)"
fi
while IFS= read -r c; do
  [[ -n "$c" ]] && commits+=("$c")
done <<< "$src"

if [[ ${#commits[@]} -eq 0 ]]; then
  echo "check_no_ai_attribution: no commits in range; nothing to check."
  exit 0
fi

fail=0
for sha in "${commits[@]}"; do
  meta="$(git show -s --format='%an%n%ae%n%cn%n%ce%n%B' "$sha")"

  if printf '%s' "$meta" | grep -qiE 'co-authored-by:[[:space:]]*claude'; then
    echo "::error::commit $sha has 'Co-Authored-By: Claude'"
    fail=1
  fi
  if printf '%s' "$meta" | grep -qiE 'generated with claude'; then
    echo "::error::commit $sha has 'Generated with Claude'"
    fail=1
  fi
  if printf '%s' "$meta" | grep -qF '🤖'; then
    echo "::error::commit $sha contains the 🤖 emoji"
    fail=1
  fi

  ident="$(git show -s --format='%an %ae %cn %ce' "$sha")"
  if printf '%s' "$ident" | grep -qiE 'claude|anthropic'; then
    echo "::error::commit $sha author/committer identity references claude/anthropic: $ident"
    fail=1
  fi
done

if [[ $fail -ne 0 ]]; then
  echo "check_no_ai_attribution: FAILED — strip all AI attribution before merge."
  exit 1
fi
echo "check_no_ai_attribution: phase 1 (commit/author) OK — ${#commits[@]} commit(s) clean."

# --- Phase 2: tracked-file CONTENT attribution scan ---
CONTENT_PATTERNS='([Cc]o-[Aa]uthored-[Bb]y:[[:space:]]*[Cc]laude)|([Gg]enerated with [Cc]laude)|(🤖)|(\bby Claude\b)|(Claude \(this session\))|(\*\*Manager:\*\*[[:space:]]*Claude)|(·[[:space:]]*claude[[:space:]]*·)'
content_hits="$(git grep -nIE "$CONTENT_PATTERNS" -- . \
  ':(exclude).github/scripts/check_no_ai_attribution.sh' \
  ':(exclude).github/pull_request_template.md' || true)"
if [[ -n "$content_hits" ]]; then
  echo "::error::AI-attribution phrasing in tracked content:"
  echo "$content_hits"
  echo "check_no_ai_attribution: FAILED — remove AI-attribution phrasing from tracked content."
  exit 1
fi
echo "check_no_ai_attribution: phase 2 (tracked content) OK — no AI-attribution phrasing."
