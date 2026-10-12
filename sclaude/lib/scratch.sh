#!/usr/bin/env bash
#
# What sclaude itself puts into a project's trees, kept out of git and out of
# every Vercel upload.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# One list, and both exclusions are built from it. They used to be two lists:
# SCRATCH_PATHS hid sclaude's paths from git, and write_vercelignore named its
# own. A feature's working directory was on the first and missing from the
# second, so every preview uploaded the worktree's plan, state, logs, local
# database settings and rendered terminal. A path added here is now covered by
# both, and tests/paths.py fails if the two ever part again. There is nothing
# to configure: a project neither names these paths nor ignores them itself.
#
# Everything sclaude keeps in a product lives in one folder, .sclaude/, so the
# product's root does not grow: config.json, team/ and people/ are the
# product's and committed; local/ is the machine's and is neither.
#
#   .sclaude/local  the machine's part: a feature's working directory,
#                   .sclaude/local/feature/ in its worktree, and the terminal
#                   recordings, .sclaude/local/terminal/ in the main tree
#   .vercelignore   this file's own output, in every tree sclaude deploys. It
#                   is the one thing at the root, because Vercel reads it only
#                   there
SCRATCH_PATHS=(.sclaude/local .vercelignore)

# The main repository of a tree, or of the current directory. Nothing outside
# a repository.
scratch_root() {
  local common
  common="$(git -C "${1:-.}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 1
  dirname "$common"
}

# Hides the list from git through the repository's .git/info/exclude: it is
# machine-local, read by every worktree of the repository (git reads only the
# main one's) and needs no edit to the project's .gitignore, which would have
# to go through a pull request. Until then an internal file would surface as
# "uncommitted changes" in the clean-up, where the question must mean "you are
# about to lose work". Called before sclaude creates any of these paths, so
# there is no moment git could see one.
#
#   scratch_hide [tree]   the current directory's repository without one
scratch_hide() {
  local root exclude p
  root="$(scratch_root "${1:-.}")" || return 0
  exclude="$root/.git/info/exclude"
  [[ -d "$root/.git" ]] || return 0
  mkdir -p "$root/.git/info" 2>/dev/null || return 0
  for p in "${SCRATCH_PATHS[@]}"; do
    grep -qxF "$p" "$exclude" 2>/dev/null && continue
    printf '\n# Written by sclaude in feature worktrees; machine-local.\n%s\n' "$p" \
      2>/dev/null >> "$exclude" || return 0
  done
}

# What a tree's .vercelignore must hold and does not, one line each. The CLI
# reads .vercelignore and a short list of its own, never .gitignore or
# .git/info/exclude, so a path git never sees still goes up with a deploy.
# Two lines beyond the list: .env and .env.* are symlinks to the main
# repository's files, which outside this machine point nowhere, and the build
# dies; Vercel takes its own environment values. The rest are the list,
# anchored, without a trailing slash so a symlink is matched as well as a
# directory. A line written with a trailing slash counts as the same.
vercelignore_missing() {
  local f="$1/.vercelignore" line p
  for line in .env '.env.*'; do
    grep -qxF -- "$line" "$f" 2>/dev/null || echo "$line"
  done
  for p in "${SCRATCH_PATHS[@]}"; do
    grep -qxF -e "/$p" -e "/$p/" "$f" 2>/dev/null || echo "/$p"
  done
}

# Whether the project tracks a tree's .vercelignore itself. Then it is the
# project's file, and sclaude says what it lacks rather than editing it.
vercelignore_tracked() {
  git -C "$1" ls-files --error-unmatch .vercelignore >/dev/null 2>&1
}

# Brings a tree's .vercelignore up to what vercelignore_missing wants: a
# feature's worktree before a preview, the main repository before production.
# Only the missing lines are appended, so a hand edit stays, an old file is
# brought up to date, and it is safe before every deploy.
write_vercelignore() {
  # Two declarations rather than one, for the reason three other files in this
  # library already record: bash assigns a `local` list left to right and does
  # not see a name from the same command, so `local wt="$1" f="$wt/..."` made
  # `f` into `/.vercelignore`. The existence check then asked about a file at
  # the filesystem root, and the write went there too — failing silently for
  # want of permission. The upshot was that no worktree ever got the file, and
  # every preview went up carrying the `.env` symlinks it exists to exclude.
  local wt="$1"
  local f="$wt/.vercelignore" missing
  [[ -n "$wt" && -d "$wt" ]] || return 0
  missing="$(vercelignore_missing "$wt")"
  [[ -n "$missing" ]] || return 0
  if vercelignore_tracked "$wt"; then
    warn "  $f is the project's own and lacks: $(tr '\n' ' ' <<< "$missing")"
    warn "  a deploy uploads those; add them to it"
    return 0
  fi
  {
    [[ -s "$f" ]] || echo "# Written by sclaude (scratch.sh): what a deploy must not upload."
    # A file that does not end in a newline would take the first line in as
    # part of its last: node_modules.env.
    [[ -s "$f" && -n "$(tail -c 1 "$f")" ]] && echo ""
    printf '%s\n' "$missing"
  } 2>/dev/null >> "$f" || true
}
