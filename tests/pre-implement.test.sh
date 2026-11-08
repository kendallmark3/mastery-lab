#!/usr/bin/env bash
# Tests for hooks/pre-implement.sh and hooks/pre-implement-hook.sh. Run from anywhere: bash tests/pre-implement.test.sh
set -uo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
hook="$root/hooks/pre-implement.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
failures=0

expect() {
  local want="$1" label="$2" file="$3" got=0
  bash "$hook" "$file" >"$tmp/out" 2>&1 || got=$?
  if [ "$want" = pass ] && [ "$got" -eq 0 ]; then echo "ok   - $label"
  elif [ "$want" = fail ] && [ "$got" -ne 0 ]; then echo "ok   - $label"
  else echo "FAIL - $label (exit $got)"; sed 's/^/       /' "$tmp/out"; failures=$((failures + 1))
  fi
}

# The project now has a real intent; test the gate against a blank scaffold copy instead.
printf '# Current Feature\n\n## Outcome\n\n## Inputs\n\n## Outputs\n\n## Success / Evidence\n\n## Constraints / Boundaries\n' >"$tmp/blank-current-feature.md"
expect fail "blank current-feature.md is not sufficient" "$tmp/blank-current-feature.md"
expect pass "this project's current-feature.md is sufficient" "$root/intent/current-feature.md"
expect fail "blank feature template is not sufficient" "$root/templates/feature-template.md"
expect fail "missing file fails" "$tmp/does-not-exist.md"

cat >"$tmp/new.md" <<'EOF'
# Current Feature

## Outcome
Operators can see failed jobs at a glance.

## Success / Evidence
A failed job is visible on the dashboard without scrolling.
EOF
expect pass "outcome and evidence alone are sufficient" "$tmp/new.md"

cat >"$tmp/old.md" <<'EOF'
# Current Feature
Business Outcome
Operators can see failed jobs at a glance.
Requirements
Constraints
Acceptance Criteria
A failed job is visible on the dashboard without scrolling.
EOF
expect pass "previous format is still accepted" "$tmp/old.md"

cat >"$tmp/no-evidence.md" <<'EOF'
# Current Feature

## Outcome
Operators can see failed jobs at a glance.

## Success / Evidence

## Constraints / Boundaries
Do not change the backend.
EOF
expect fail "outcome without evidence is not sufficient" "$tmp/no-evidence.md"
if grep -q "Success / Evidence" "$tmp/out" && ! grep -q -- "- Outcome" "$tmp/out"; then
  echo "ok   - names only the missing section"
else
  echo "FAIL - names only the missing section"; failures=$((failures + 1))
fi

cat >"$tmp/comments.md" <<'EOF'
# Current Feature

## Outcome
<!-- What should be true when this is done? -->

## Success / Evidence
<!-- How will we know? -->
EOF
expect fail "guidance comments do not count as content" "$tmp/comments.md"

cat >"$tmp/delta.md" <<'EOF'
# Current Feature

## Outcome
Operators can see failed jobs at a glance.

## Success / Evidence
A failed job is visible on the dashboard without scrolling.

# Intent Delta

## Observation
The dashboard feels too busy.

## Change
Make failures obvious.
EOF
expect pass "an appended delta keeps the intent sufficient" "$tmp/delta.md"

# --- hooks/pre-implement-hook.sh: the Claude Code PreToolUse wrapper ---
gate="$root/hooks/pre-implement-hook.sh"

expect_gate() {
  local want="$1" label="$2" project="$3" target="$4" got=0
  printf '{"tool_name":"Write","tool_input":{"file_path":"%s","content":"x"}}' "$target" |
    CLAUDE_PROJECT_DIR="$project" bash "$gate" >"$tmp/out" 2>&1 || got=$?
  if [ "$got" -eq "$want" ]; then echo "ok   - $label"
  else echo "FAIL - $label (exit $got, wanted $want)"; sed 's/^/       /' "$tmp/out"; failures=$((failures + 1))
  fi
}

mkdir -p "$tmp/no-intent" "$tmp/blank/intent" "$tmp/ready/intent"
cp "$root/templates/feature-template.md" "$tmp/blank/intent/current-feature.md"
cp "$tmp/new.md" "$tmp/ready/intent/current-feature.md"

expect_gate 0 "hook leaves projects without an intent file alone" "$tmp/no-intent" "$tmp/no-intent/app.py"
expect_gate 2 "hook blocks code edits while the intent is blank" "$tmp/blank" "$tmp/blank/src/app.py"
expect_gate 0 "hook never blocks Markdown, so the intent can be written" "$tmp/blank" "$tmp/blank/intent/current-feature.md"
expect_gate 0 "hook allows code edits once the intent is sufficient" "$tmp/ready" "$tmp/ready/src/app.py"

mkdir -p "$tmp/starter/intent" "$tmp/starter/.claude-plugin" "$tmp/other-plugin/intent" "$tmp/other-plugin/.claude-plugin"
cp "$root/templates/feature-template.md" "$tmp/starter/intent/current-feature.md"
cp "$root/templates/feature-template.md" "$tmp/other-plugin/intent/current-feature.md"
cp "$root/.claude-plugin/plugin.json" "$tmp/starter/.claude-plugin/plugin.json"
echo '{ "name": "some-other-plugin" }' >"$tmp/other-plugin/.claude-plugin/plugin.json"
expect_gate 0 "hook skips the starter's own repository" "$tmp/starter" "$tmp/starter/hooks/x.sh"
expect_gate 2 "hook still gates other plugin repositories" "$tmp/other-plugin" "$tmp/other-plugin/src/app.py"

if [ "$failures" -ne 0 ]; then
  echo "$failures test(s) failed"
  exit 1
fi
echo "all tests passed"
