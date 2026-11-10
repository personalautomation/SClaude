#!/usr/bin/env bash
#
# The merge, when QA has passed and nothing is in the way: what stands in its
# way, how it is made, the offer and the wait for it.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# --- the merge, when QA has passed and nothing is in the way -----------------
#
# The merge is the human's step, and it stays theirs unless the project set
# `merge` to auto: nothing else below merges on its own. What changes is where the decision is put in front of them. Until
# now the cycle reached this point and printed "Merge PR #N, then run: sclaude
# done" — a instruction to go elsewhere, do a thing, and come back. Whenever QA
# has already passed the issue and GitHub says the pull request is clean, that
# errand is one keystroke's worth of work standing between a finished feature
# and production, and sclaude is holding both ends of it.
#
# So the offer is made here and only here: after the preview deploy and after
# the preview regression, because those are what make the branch worth merging
# at all. Offering earlier would be offering to merge something nobody has
# checked.
#
# Three things have to hold before a question is worth asking, and each one
# that does not is a sentence saying so rather than silence — a feature that
# stands for a day because nobody said "waiting for a review" is the failure
# this replaces.

# What GitHub says about merging this pull request, as one word:
#
#   ready     — mergeable, clean, and ours to merge
#   excused   — as ready, but GitHub calls it UNSTABLE only for checks the
#               verdict does not count: a stale findings check, a run a newer
#               one took over, the Actions checks of a review here (merge_red);
#               merged like ready, said differently
#   dirty     — conflicts with main
#   blocked   — a required review or check is missing
#   behind    — main has moved and the branch must catch up
#   unstable  — checks are still running or one of them is red
#   draft     — still a draft
#   norights  — we cannot merge it: someone else's repository, or no push
#   unknown   — gh could not answer, or GitHub has not computed it yet
#
# `mergeable` is computed lazily on GitHub's side: the first ask on a freshly
# pushed branch answers UNKNOWN, and the answer arrives a second or two later.
# That is not a state to report to anybody — it is "ask again" — so the caller
# treats unknown as a reason to say nothing rather than a reason to complain.
#
# With the feature's tree, `unstable` is looked at closer: when the one red
# check is the findings check and every finding it lists is resolved by now
# or one the person decided to leave (merge_red in pr_context.py), it is
# `excused`, which callers merge as `ready` and the question words as it is
# — not "nothing open": a kept thread may be. The check is not run again when
# a thread is resolved, so GitHub calls the pull request UNSTABLE for as long
# as nobody pushes, and a `merge: auto` feature waited on it for ever.
#
#   merge_readiness <pr> [worktree]
merge_readiness() {
  local pr="$1" wt="${2:-}" repo json word
  [[ -n "$pr" && "$pr" != "null" ]] || { echo unknown; return 0; }
  command -v gh >/dev/null 2>&1 || { echo unknown; return 0; }
  repo="$(gh_repo)" || { echo unknown; return 0; }

  # viewerCanUpdate is the rights question. It is not the same as "can merge" —
  # GitHub has no field that answers that exactly — but it is the closest one
  # that exists: it is false for a fork's pull request opened against somebody
  # else's repository, which is the case this is guarding against. A protected
  # branch that refuses the merge for a reason of its own shows up as `blocked`
  # in mergeStateStatus, which is checked below.
  #
  # All of it from GraphQL, in one call per poll: `gh pr view --json` no
  # longer takes viewerCanUpdate, and asking for it there failed the whole
  # call — every answer was `unknown`, and a `merge: auto` pull request
  # waited, clean, for ever.
  json="$(gh api graphql \
    -f query='query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p){mergeable mergeStateStatus isDraft state viewerCanUpdate}}}' \
    -f o="${repo%%/*}" -f n="${repo#*/}" -F p="$pr" \
    --jq .data.repository.pullRequest 2>/dev/null)" || { echo unknown; return 0; }
  [[ -n "$json" && "$json" != "null" ]] || { echo unknown; return 0; }

  word="$(MERGE_JSON="$json" python3 - <<'PYREADY'
import json, os

try:
    pr = json.loads(os.environ["MERGE_JSON"])
except Exception:
    print("unknown")
    raise SystemExit(0)

if pr.get("state") != "OPEN":
    print("unknown")
elif pr.get("isDraft"):
    print("draft")
elif not pr.get("viewerCanUpdate", True):
    print("norights")
else:
    # mergeStateStatus is the specific answer and mergeable the general one, so
    # the specific is read first: MERGEABLE with a BLOCKED state is a pull
    # request with no conflicts that still cannot be merged, and calling that
    # "ready" is exactly the mistake worth avoiding.
    state = (pr.get("mergeStateStatus") or "").upper()
    mergeable = (pr.get("mergeable") or "").upper()
    if mergeable == "CONFLICTING" or state == "DIRTY":
        print("dirty")
    elif state == "CLEAN" and mergeable == "MERGEABLE":
        print("ready")
    elif state == "BLOCKED":
        print("blocked")
    elif state == "BEHIND":
        print("behind")
    elif state == "UNSTABLE":
        print("unstable")
    else:
        # HAS_HOOKS and anything GitHub adds later. Not "ready" — we only claim
        # that for the one state we understand completely.
        print("unknown")
PYREADY
)"
  if [[ "$word" == unstable && -n "$wt" ]] \
     && [[ "$(python3 "$LIB/review/pr_context.py" --merge-red "$wt" "$pr" "$repo" 2>/dev/null)" == stale ]]; then
    word=excused
  fi
  echo "$word"
}

# Why a merge is not on offer, in a human's words. Empty for the states the
# caller says nothing about.
merge_obstacle() {
  case "$1" in
    dirty)    echo "it conflicts with main — resolve them and push" ;;
    blocked)  echo "GitHub is holding it: a required review or check is missing" ;;
    behind)   echo "main has moved on — the branch has to catch up first" ;;
    unstable) echo "its checks have not all gone green" ;;
    draft)    echo "it is still a draft" ;;
    norights) echo "we have no rights to merge it here" ;;
    *)        echo "" ;;
  esac
}

# The merge flag this repository allows, preferring squash.
#
# Asked rather than assumed: `gh pr merge --squash` fails outright in a
# repository where squash merging is switched off, and the failure arrives
# after the human has already said yes — the worst moment for it. The
# preference is squash because a feature branch is a cycle's worth of
# step-by-step commits and main wants one.
#
# Falls back to --squash when gh cannot answer: it is what this project uses,
# and a wrong guess here costs a refused command, not a bad merge.
merge_method() {
  local repo json
  repo="$(gh_repo)" || { echo "--squash"; return 0; }
  json="$(gh repo view "$repo" \
            --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed \
            2>/dev/null)" || { echo "--squash"; return 0; }
  [[ -n "$json" ]] || { echo "--squash"; return 0; }

  MERGE_REPO_JSON="$json" python3 - <<'PYMETHOD'
import json, os

try:
    repo = json.loads(os.environ["MERGE_REPO_JSON"])
except Exception:
    print("--squash")
    raise SystemExit(0)

for key, flag in (("squashMergeAllowed", "--squash"),
                  ("mergeCommitAllowed", "--merge"),
                  ("rebaseMergeAllowed", "--rebase")):
    if repo.get(key):
        print(flag)
        break
else:
    print("--squash")
PYMETHOD
}

# Offers the merge when QA has passed and GitHub says the way is clear; says
# what is in the way when it is not. Returns 0 if the merge happened, 2 when
# it was put and answered — a person said no, or GitHub refused the merge —
# and 1 when it was not offered at all.
#
# The QA condition is the whole point of the timing. "In Done" is a person's
# statement that they looked at the deployment and it was good — the one thing
# sclaude cannot establish for itself and will not claim. Until that statement
# exists there is nothing to offer: the branch is deployed and green, and the
# checking has not been done. So an issue anywhere else, or no issue at all,
# gets the reminder it always got.
#
# --delete-branch is not passed. `sclaude done` removes the worktree, the local
# branch and the remote one together, and it is what the human is told to run
# next; deleting the remote here would leave that command tearing down half of
# a thing it no longer recognises.
#
# `merge` in the project's config (project_flow_mode) decides who says yes:
# `github` keeps the question out of sclaude altogether — the merge is clicked
# there, and merge_wait waits for it; `auto` answers it without asking, on
# the same conditions; `both` asks.
#
# Before either, what the merge would put on main is built (merge_build_check,
# with the feature's tree <wt>): red is not offered at all, and when it cannot
# be told, `auto` asks rather than merging.
merge_offer() {
  local slug="$1" pr="$2" issue="$3" mode="${4:-}" wt="${5:-}"
  local column ready obstacle method answer who built=0 failed
  # The history's way out of the question: merged, or on to the wait. From
  # inside the wait (MERGE_IN_WAIT, merge_wait) only a merge is a way taken.
  merge_way() {
    [[ -n "$wt" ]] || return 0
    if [[ "$1" == merged && -n "${MERGE_IN_WAIT:-}" ]]; then
      cycle_edge "$wt" merge_wait merged "${@:2}"
    elif [[ "$1" == merged ]]; then
      cycle_edge "$wt" merge merged "${@:2}"
    elif [[ -z "${MERGE_IN_WAIT:-}" ]]; then
      cycle_edge "$wt" merge merge_wait "${@:2}"
    fi
  }

  [[ -n "$pr" && "$pr" != "null" ]] || return 1
  command -v gh >/dev/null 2>&1 || return 1
  who="$(project_flow_mode merge)"
  # A feature built in parts goes to main only with every part merged into
  # its branch and none left open: a part's pull request whose base vanished
  # with the merge would be closed by GitHub unmerged (parts.sh).
  if [[ -n "$wt" ]] && declare -F parts_split >/dev/null && parts_split "$wt/.sclaude/local/feature/state.json"; then
    parts_check_say "$wt" final || return 1
  fi

  # QA's word, where there is a board to carry it.
  #
  # "In Done" is a person saying they looked at the deployment, and it is the
  # one thing sclaude cannot establish for itself. Where an issue exists and
  # has not reached that column, there is nothing to offer yet: the checking is
  # still ahead, and asking now would be asking somebody to skip it.
  #
  # A feature started from a name alone has no issue and never will. Treating
  # that as "QA has not passed" would mean it never gets an offer however green
  # it is — punishing the absence of a board rather than the absence of a
  # check, and leaving the one kind of feature where nobody else is watching to
  # the errand this replaces. So the offer stands, and the question carries the
  # difference instead: qa_checked decides which of the two is asked.
  #
  # The same shape as the production question above, and for the same reason —
  # one question, with the warning inside it. A second prompt about the same
  # decision is answered the way repeated prompts always are.
  #
  # `nodeploy` is a change nothing deploys (no_change.sh): there is no preview
  # for QA to look at, so their column is not waited for, and the review is
  # what the merge rests on.
  local qa_checked=0
  # No `board.columns.done` in the project means no column will ever carry
  # QA's word — the same as an issue on no board, and treated the same.
  if [[ "$mode" == nodeploy ]]; then
    :
  elif [[ -n "$issue" && "$issue" != "null" && -n "$QA_DONE" ]]; then
    column="$(issue_status_now "$issue" 2>/dev/null || true)"
    if column_is "$column" "$QA_DONE"; then
      qa_checked=1
    elif [[ -n "$column" ]]; then
      # The issue is on a board and sits somewhere before Done: the board is
      # being kept, so its answer is worth waiting for. The caller's reminder
      # stands, and this is the one case that stays silent.
      return 1
    fi
    # An empty answer is not a column before Done. issue_status_now says
    # nothing for three different situations — the issue is on no board at
    # all, gh is silent, the network is down — and none of them is QA still
    # working. Reading them as "not yet" would hold the offer back for ever on
    # a repository with no project board, which is the same mistake as
    # demanding an issue that will never exist. So it falls through with
    # qa_checked at 0 and is asked the unchecked question.
  fi

  ready="$(merge_readiness "$pr" "$wt")"

  if [[ "$ready" != ready && "$ready" != excused ]]; then
    obstacle="$(merge_obstacle "$ready")"
    # `unknown` says nothing: gh was silent, or GitHub has not finished
    # computing mergeability. Naming a state we do not know is how a tool
    # teaches people to stop reading it.
    [[ -n "$obstacle" ]] || return 1
    echo ""
    if [[ "$qa_checked" -eq 1 ]]; then
      warn "QA passed issue #$issue, but PR #$pr cannot be merged yet:"
    else
      warn "PR #$pr cannot be merged yet:"
    fi
    info "  $obstacle."
    merge_way wait github "merge readiness" note="$obstacle"
    return 1
  fi
  # What is in the way is worth saying in every mode; the question is not
  # sclaude's to ask when the merge is clicked on GitHub.
  [[ "$who" != github ]] || { merge_way wait setting "merge=github"; return 1; }

  failed="$(merge_build_check "$wt")" || built=$?
  if [[ "$built" -eq 1 ]]; then
    echo ""
    warn "PR #$pr merged with the newer main fails \`$failed\` — not merging it from here."
    info "  The log: $wt/.sclaude/local/feature/merge-check.log (the earlier checks and runs.tsv in logs/merge-check/)"
    info "  Merge main into the branch and fix it; then: $SELF $slug"
    merge_way wait sclaude "the merge with the newer main built" note="fails: $failed"
    return 2
  fi

  method="$(merge_method)"

  # The question, and what it rests on. Two headings and two wordings, because
  # they are two different things to agree to: one is backed by a person's
  # sign-off, the other by the suite alone. Saying so is the whole protection
  # available here — the repository is private on a free plan, where branch
  # protection is refused, so nothing but the wording stands between a green
  # preview and main.
  local prompt clean="is clean: no conflicts, nothing GitHub is holding it for."
  # The one red check is the findings check, gone stale: GitHub shows it red,
  # and "clean" above it would be the one line here that is not true.
  [[ "$ready" == excused ]] \
    && clean="has no conflicts; its one red check is the findings check, red only for threads resolved since it ran or left to you."
  echo ""
  if [[ "$mode" == nodeploy ]]; then
    say "${BOLD}PR #$pr changes nothing that deploys — no preview, no QA on one.${OFF}"
    say "${DIM}It $clean${OFF}"
    say "${DIM}The review is what this rests on.${OFF}"
    prompt="Merge it now?"
  elif [[ "$qa_checked" -eq 1 ]]; then
    say "${BOLD}QA passed issue #$issue — it is in '$QA_DONE'.${OFF}"
    say "${DIM}PR #$pr $clean${OFF}"
    prompt="Merge it now?"
  else
    # Two ways to arrive here, and they are worth telling apart: a feature with
    # no issue at all, and an issue that is on no board. Both mean the same
    # thing for the decision — no column will ever say QA looked — but a person
    # reading "no issue" about a feature that plainly has one stops trusting
    # the line.
    if [[ -n "$issue" && "$issue" != "null" ]]; then
      say "${BOLD}Issue #$issue is on no board — nothing will say whether QA looked.${OFF}"
    else
      say "${BOLD}No issue on GitHub for this one — nobody signed off on the deployment.${OFF}"
    fi
    say "${DIM}The preview regression is green and PR #$pr $clean${OFF}"
    say "${DIM}That is all this rests on.${OFF}"
    prompt="Merge it unchecked?"
  fi

  # The acceptance criteria as QA left them in the issue — the business record
  # of the feature, and where QA works. Shown inside this question rather than
  # asked about in a second one: with the issue in Done a person has already
  # signed off, and a separate "some boxes are empty, merge anyway?" would be
  # two prompts for one decision. The boxes are not a gate either — an empty one
  # may mean "not looked at yet" as easily as "does not work" — so the most they
  # do is put their own names into the question, beside what it already says:
  # "unchecked" stays when nobody signed off, because that word is the warning.
  local criteria="" unticked="" line
  if [[ -n "$issue" && "$issue" != "null" ]]; then
    criteria="$(python3 "$LIB/cycle/acceptance.py" --status "$issue" "${REPO:-.}" 2>/dev/null || true)"
  fi
  if [[ -n "$criteria" ]]; then
    echo ""
    say "Acceptance criteria in issue #$issue:"
    while IFS= read -r line; do say "  $line"; done <<<"$criteria"
    unticked="$(python3 "$LIB/cycle/acceptance.py" --unticked "$issue" "${REPO:-.}" 2>/dev/null || true)"
    if [[ -n "$unticked" && "$mode" == nodeploy ]]; then
      prompt="Not ticked in issue #$issue: $unticked. Merge anyway?"
    elif [[ -n "$unticked" && "$qa_checked" -eq 1 ]]; then
      prompt="QA passed it, but not ticked in issue #$issue: $unticked. Merge anyway?"
    elif [[ -n "$unticked" ]]; then
      prompt="Merge it unchecked? Not ticked in issue #$issue either: $unticked."
    fi
  fi
  echo ""
  say "  gh pr merge $pr $method"
  echo ""
  # Auto answers only on QA's word (or for a change nothing deploys, where
  # the review is the whole check). Without it — no issue, no board, gh
  # silent about the column — the question is put to a person as before:
  # an empty answer about the board is not a pass.
  local merge_by=setting merge_how="merge=auto"
  if [[ "$who" == auto && "$built" -eq 0 ]] && [[ "$qa_checked" -eq 1 || "$mode" == nodeploy ]]; then
    say "${BOLD}Merging: \`merge\` is auto in the project config (\`$SELF config\`).${OFF}"
  else
    if [[ "$who" == auto && "$built" -ne 0 ]]; then
      info "  \`merge\` is auto, but its merge with the newer main could not be built here — so it is asked."
    elif [[ "$who" == auto ]]; then
      info "  \`merge\` is auto, but nothing says QA passed it — so it is asked."
    fi
    ask "${BOLD}$prompt [y/n] ${OFF}" answer yn && merge_by=person || merge_by=none
    merge_how="$ASKED_HOW"
    if ! is_yes "$answer"; then
      info "→ Merge: skipped. It stays yours to do."
      merge_way wait "$merge_by" "$merge_how"
      return 2
    fi
  fi

  if ! gh pr merge "$pr" --repo "$(gh_repo)" "$method"; then
    echo ""
    warn "  ✗ The merge did not go through — GitHub refused it."
    info "  Nothing here changed; merge it on GitHub and carry on with: $SELF $slug"
    merge_way wait github "gh pr merge" note="GitHub refused the merge"
    return 2
  fi

  echo ""
  echo "${GREEN}✓ PR #$pr merged.${OFF}"
  merge_way merged "$merge_by" "$merge_how"
  [[ -n "$wt" ]] && history_add "$wt/.sclaude/local/feature/state.json" merge merged
  return 0
}

# Wait until the pull request is merged.
#
#   merge_wait <slug> <issue> <pr> <branch>
#
# The merge is the one step of the cycle that is a person's alone. This comes
# after merge_offer: either the person said no to merging from here, or GitHub
# named something in the way, and either way the merge happens on GitHub and
# this notices it. A `gh` call every MERGE_POLL seconds costs nothing.
#
# Returns 0 once merged, 1 with no branch to ask about, 2 when the pull request
# was closed without a merge — it can never be merged then, and waiting on it
# would last for ever — and 3 when the branch stopped merging with main while
# it waited (merge_conflicts, asked every SYNC_POLL seconds with the worktree
# given): nobody can merge it then, and the sync with main is the caller's.
#
# `merge` in the project's config (project_flow_mode) adds a way out: with
# `both`, `m` pressed here puts the merge question again; with `auto`, the
# merge is made the first time GitHub calls the pull request ready — once,
# or again after a red check once the pair moves. <offer-mode> is merge_offer's.
#
#   merge_wait <slug> <issue> <pr> <branch> [offer-mode] [worktree]
merge_wait() {
  local slug="$1" issue="$2" pr="$3" branch="$4" offer_mode="${5:-}" wt="${6:-}"
  local waited=0 logged=0 start=$SECONDS mode held=none answered=0 keys="" offered red
  local looked=0 conflict_rc

  [[ -n "$branch" ]] || return 1
  mode="$(project_flow_mode merge)"
  [[ "$mode" == both ]] && keys=", m merges here"
  echo ""
  info "Waiting for the merge of PR #$pr${issue:+ (issue #$issue)}; merge it on GitHub."
  [[ "$mode" == both ]] && info "  Or press m here to merge it from sclaude."
  # Held by the check of the merge with main (merge_build_check): the offer
  # just before said so, and "merges it itself" right under it is not what
  # happens. It is tried again once the branch or main moves.
  red="$(merge_check_red "$wt")"
  if [[ "$mode" == auto && -n "$red" ]]; then
    held="$(merge_check_pair "$wt")"
    info "  \`merge\` is auto, but held: the merge with main fails \`$red\`. sclaude tries"
    info "  again once the branch or main moves; or merge it on GitHub."
  elif [[ "$mode" == auto ]]; then
    info "  \`merge\` is auto: sclaude merges it itself once GitHub calls it ready."
  fi
  info "  Ctrl-C to leave — the feature resumes here with: $SELF $slug"
  echo ""
  [[ -n "$wt" ]] && history_add "$wt/.sclaude/local/feature/state.json" merge wait
  local pr_state
  while pr_state="$(branch_pr_state "$branch")"; [[ "$pr_state" != "MERGED" ]]; do
    if [[ "$pr_state" == "CLOSED" ]]; then
      [[ -t 1 ]] && printf '\r\033[2K'
      echo ""
      alarm "PR #$pr was closed without being merged — nothing to wait for."
      info "  Reopen it, or open a new one from the branch; then: $SELF $slug"
      return 2
    fi
    if [[ -t 1 ]]; then
      printf '\r\033[2K\033[?7l  %sHuman in the loop%s — waiting for the merge (%s so far, next check in %ss, any key checks now%s)\033[?7h' \
        "$DIM" "$OFF" "$(regression_duration "$waited")" "$MERGE_POLL" "$keys"
    elif [[ $((waited - logged)) -ge 300 || "$waited" -eq 0 ]]; then
      info "  waiting for the merge of PR #$pr${issue:+ (issue #$issue)} ($(regression_duration "$waited"))"
      logged="$waited"
    fi
    poll_pause "$MERGE_POLL"
    waited=$((SECONDS - start))
    # Asked of an open pull request only: one merged during the pause has its
    # branch deleted on GitHub, and the stale ref left here may well conflict
    # with the main that the merge moved.
    if [[ -n "$wt" && $((waited - looked)) -ge "$SYNC_POLL" ]] \
       && [[ "$(branch_pr_state "$branch")" == OPEN ]]; then
      looked="$waited"
      conflict_rc=0
      merge_conflicts "$wt" >/dev/null || conflict_rc=$?
      if [[ "$conflict_rc" -eq 1 ]]; then
        [[ -t 1 ]] && printf '\r\033[2K'
        echo ""
        warn "Main has moved, and PR #$pr no longer merges with it."
        return 3
      fi
    fi
    # Auto stops trying once the merge was put and answered (2): a person's
    # "no", or GitHub refusing it, repeated every poll is noise. A red check
    # of the merge with main holds it only until the branch or main moves —
    # fetched by the conflict check above — when it is a new merge to put.
    # Not offered (1) — the column read empty, GitHub still computing — is
    # tried again on the next poll.
    if [[ "$mode" == both && "$POLL_KEY" == [mM] ]]; then
      [[ -t 1 ]] && printf '\r\033[2K'
      offered=0
      MERGE_IN_WAIT=1 merge_offer "$slug" "$pr" "$issue" "$offer_mode" "$wt" || offered=$?
      [[ "$offered" -eq 0 ]] && return 0
      [[ "$offered" -eq 1 ]] \
        && info "  Nothing to merge from here yet: QA has not passed it, or GitHub has not called it ready."
    elif [[ "$mode" == auto && "$answered" -eq 0 && "$held" != "$(merge_check_pair "$wt")" \
            && "$(merge_readiness "$pr" "$wt")" =~ ^(ready|excused)$ ]]; then
      [[ -t 1 ]] && printf '\r\033[2K'
      offered=0
      MERGE_IN_WAIT=1 merge_offer "$slug" "$pr" "$issue" "$offer_mode" "$wt" || offered=$?
      [[ "$offered" -eq 0 ]] && return 0
      if [[ "$offered" -eq 2 ]]; then
        if [[ -n "$(merge_check_red "$wt")" ]]; then
          held="$(merge_check_pair "$wt")"
        else
          answered=1
        fi
      fi
    fi
  done
  [[ -t 1 ]] && printf '\r\033[2K'
  echo "${GREEN}✓ PR #$pr merged.${OFF}"
  [[ -n "$wt" ]] && cycle_edge "$wt" merge_wait merged github "merged on GitHub"
  [[ -n "$wt" ]] && history_add "$wt/.sclaude/local/feature/state.json" merge merged
  return 0
}
