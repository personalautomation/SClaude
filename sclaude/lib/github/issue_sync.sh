#!/usr/bin/env bash
#
# The issue's summary, kept in step with the feature: its body, its comments
# and its checkboxes, written from what the steps left.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# A summary of the work's progress — in the issue the feature was created from.
#
# Until now the link was one-way: the issue was read to choose a feature and
# start the plan, and was not touched again. The issue meanwhile said nothing
# about anything — an issue closed with a merge and zero comments, and from it
# one could learn neither that the work had happened nor what it was done with.
#
# One comment, rewritten at every transition, rather than a feed: a feed repeats
# what is visible in the PR, and has to be read from the bottom up to understand
# where the work stands. We find our own comment by a marker in the first line —
# `gh issue comment --edit-last` will not do, twice over: gh 2.45.0 (which is
# what is installed here) has no --create-if-none, so the first call would fail,
# and "the author's last comment" is not necessarily our summary.
#
# It breaks nothing: no issue, no gh, no network and we warn and carry on.
# Reporting is not worth stalling a step over.
issue_sync() {
  # Two declarations rather than one: in `local a="$1" b="$a/x"` bash under
  # set -u trips over the $a that does not exist yet.
  local wt="$1"
  local state="$wt/.sclaude/local/feature/state.json" issue repo body id

  issue="$(state_get "$state" issue || true)"
  [[ -n "$issue" && "$issue" != "null" ]] || return 0
  command -v gh >/dev/null 2>&1 || return 0
  repo="$(gh_repo)" || return 0
  [[ -n "$repo" ]] || return 0

  # The steps' order and names come from STEP_SPEC rather than being repeated
  # here as a fifth copy: while they lived as a separate dictionary, an added
  # step made it into the cycle but not into the issue's summary.
  local spec="" st
  for st in "${STEPS[@]}"; do
    spec+="$st=$(step_title "$st")"$'\n'
  done

  # What each friction review actually changed in the orchestrator.
  #
  # run_friction records the instruments HEAD on either side of a review that
  # committed; here those ranges become commit subjects. The reading is done in
  # shell rather than inside the heredoc because git lives in sclaude's checkout and
  # the summary is assembled from the product's worktree — and because
  # INSTRUMENTS is not exported, so the child python cannot see it anyway.
  #
  # One line per commit, `key<TAB>sha<TAB>subject<TAB>files`, the last being
  # the paths the commit touched, space-separated: the renderer needs them to
  # give each commit of a `mixed` review a verdict of its own. A range whose commits have
  # since been rewritten or dropped yields nothing, and the review falls back to
  # the verdict-only row below — or to no row at all, if it left no verdict
  # either. A summary is not worth failing over, and a row naming a sha that no
  # longer resolves would send a reader after a commit they cannot open.
  #
  # A review earns a row if it committed or if it left a verdict. The second is
  # how a `deliberate` outcome appears at all: it changed nothing on purpose, so
  # it has no range and `git log` has nothing to say about it — and that is the
  # ordinary outcome of a review, not a rare one.
  local fixes="" fkey ffrom fto
  for fkey in $(python3 - "$state" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1]) as fh:
        reviews = json.load(fh).get("friction") or {}
except (OSError, ValueError):
    reviews = {}
for key, node in reviews.items():
    if not isinstance(node, dict):
        continue
    if ((node.get("project_from") and node.get("project_to"))
            or (node.get("from") and node.get("to")) or node.get("verdict")):
        print(key)
PY
  ); do
    # A review commits into the product now, on the feature's branch: that
    # range, read in the worktree. A state from before then may still carry
    # an orchestrator range, read where it was made.
    local fgit="$wt"
    ffrom="$(state_get "$state" "friction.$fkey.project_from" || true)"
    fto="$(state_get "$state" "friction.$fkey.project_to" || true)"
    if [[ -z "$ffrom" || -z "$fto" ]]; then
      fgit="$INSTRUMENTS"
      ffrom="$(state_get "$state" "friction.$fkey.from" || true)"
      fto="$(state_get "$state" "friction.$fkey.to" || true)"
    fi
    if [[ -n "$ffrom" && -n "$fto" ]]; then
      while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        fixes+="$fkey"$'\t'"$line"$'\t'"$(git -C "$fgit" diff-tree \
          --no-commit-id --name-only -r "${line%%$'\t'*}" 2>/dev/null \
          | tr '\n' ' ')"$'\n'
      done < <(git -C "$fgit" log --no-merges --format='%h%x09%s' \
                 "$ffrom..$fto" 2>/dev/null || true)
    else
      # No commits: one row carrying the verdict alone, with empty sha and
      # subject. The renderer fills the Change cell from the verdict's note.
      fixes+="$fkey"$'\t'$'\t'$'\n'
    fi
  done

  body="$(SCLAUDE_STEPS="$spec" SCLAUDE_FIXES="$fixes" SCLAUDE_TOTAL="$(cycle_total)" \
    PYTHONPATH="${STATE_CORE:-${LIB:-}/core}" python3 - "$state" <<'PY' 2>/dev/null
import datetime, json, os, sys
import state_file

ORDER, TITLES = [], {}
for line in os.environ.get("SCLAUDE_STEPS", "").splitlines():
    if "=" in line:
        name, title = line.split("=", 1)
        ORDER.append(name)
        TITLES[name] = title

with open(sys.argv[1]) as fh:
    s = json.load(fh)

slug = s.get("feature", "")
steps = s.get("steps") or {}
current = s.get("step", "")


def when(value):
    # 2026-09-01T08:14:03+03:00 -> 2026-09-01 08:14. Minutes are enough, and
    # the offset only gets in the way in a table.
    if not value:
        return "—"
    return value[:16].replace("T", " ")


# The friction review that followed a step or a fixing session, by its key.
#
# Reviews are kept per subject — `friction.<step>`, `friction.fix-<stage>-<n>`
# — so the column is a lookup rather than a scan. An empty cell means the log
# was empty and no review was launched, which is the ordinary case: every step
# and every fixing session gets one offered, and most have nothing to read.
reviews = s.get("friction") or {}


def friction_cell(key):
    """Every friction review for one step or fixing session, one per line.

    A subject can have several: a stalled review is followed by a new
    conversation, and a step that closes twice is reviewed twice. The node's
    own fields describe the latest; the earlier ones are read from their runs
    (session_runs, state.sh).
    """
    node = reviews.get(key)
    runs = [r for r in (node.get("runs") or []) if isinstance(r, dict)] \
        if isinstance(node, dict) else []
    # A latest pass whose log was empty opened no session, so every run is
    # an earlier review's.
    if not (isinstance(node, dict) and node.get("empty")):
        runs = runs[:-1]
    earlier = []
    for run in runs:
        sid = (run.get("session") or "")[:8]
        # A put-off had no session (friction_defer_proposals): no id to show.
        if (run.get("session") or "").startswith("deferred-"):
            earlier.append("put off")
            continue
        if run.get("stalled"):
            word = "stalled"
        elif run.get("done"):
            word = run.get("outcome") or "reviewed"
        else:
            word = "interrupted"
        earlier.append("`%s` %s" % (sid, word) if sid else word)
    return "<br>".join(earlier + [latest_friction_cell(key)])


def latest_friction_cell(key):
    """What became of the latest friction review for one step or fixing session.

    Six answers, because the dash used to stand for four different things and a
    reader could not tell which. Every one of them is written by the
    orchestrator at the moment it happens; nothing here is inferred.
    """
    node = reviews.get(key)
    if not isinstance(node, dict):
        # No node at all: the cycle has not reached this step. Not "there was no
        # friction" — nobody has looked yet.
        return "queued"
    # An empty log, recorded as such by run_friction. The ordinary case: the
    # step ran into no ban worth reporting, so no session was launched.
    if node.get("empty"):
        return "nothing"
    # Held while [g] ran step 4's rounds (friction_hold): its entries are read
    # by a later review, which says the verdict.
    if node.get("read_in") and not node.get("session") and not node.get("done"):
        return "read in %s" % node["read_in"]
    if node.get("held") and not node.get("session") and not node.get("done"):
        return "held"
    # `done` is asked before the id, and that order is the whole point. The id
    # used to be asked first, on the reasoning that a closed review has none —
    # but a review interrupted between `done` and the clearing of `session` has
    # both, and the column then called a finished review `open` for the rest of
    # the feature's life. `done` is the field that says what happened;
    # `session` only says where to return, and a closed review needs no return.
    if node.get("done"):
        # A closed review keeps its id in `was` so the column can name the
        # conversation. It is a separate field rather than `session` itself:
        # run_friction reads `session` to decide whether to resume, and an id
        # left there sends the next review into the closed conversation instead
        # of a new one.
        was = node.get("was")
        if node.get("verdict") == "deferred":
            # Put off by sclaude with no session (friction_defer_proposals).
            return "put off"
        if node.get("unread"):
            # Closed by hand through `sclaude reset`. The entries stayed in
            # .reviewed with nobody reading them.
            verdict = "unread"
        elif node.get("fixed"):
            # The review committed to the orchestrator: HEAD moved while it ran.
            verdict = "fixed"
        else:
            # It read the entries and changed nothing — every ban deliberate.
            verdict = "reviewed"
        return "`%s` %s" % (was[:8], verdict) if was else verdict
    sid = node.get("session")
    if sid:
        if node.get("stalled"):
            # claude exited at the door. The id names a transcript with nothing
            # in it, so there is no conversation to go back to — this one is
            # cleared rather than resumed.
            return "`%s` stalled" % sid[:8]
        # Interrupted with a conversation to return to, and holding the cycle
        # until `sclaude friction` or `sclaude reset` closes it.
        return "`%s` open" % sid[:8]
    return "queued"


def run_friction_cell(name, number, last, status, per_run):
    """The Friction cell for one session of a step.

    The session's own review when it has one. A session still running has had
    none yet: `queued`, whatever an older review of the step says — reading
    the step-wide key there called a reopened review step's live round
    `nothing`, an answer about an earlier pass. The step-wide key, on the last
    row, for a feature from before per-session keys. A dash for the rest:
    a session from before them, or one whose review never ran.
    """
    key = "%s-%d" % (name, number)
    if key in reviews:
        return friction_cell(key)
    if last and status == "in progress":
        return "queued"
    if last and not per_run and name in reviews:
        return friction_cell(name)
    return "—"


def fix_name(stage):
    """A regression-fixing session's name in the tables. The local run is the
    ordinary one and goes unnamed; a deployed stage is said."""
    return "fix after regression" if stage == "local" else "fix after %s regression" % stage


def fix_status_cell(stage, number):
    """How one fixing session ended.

    Five answers, and the same reasoning that gave the Friction column its six:
    a dash for every row meant a stage with four fixing sessions could not say
    which of them made it green. Every value is written by regression_gate at
    the moment it happens; nothing here is inferred from the stage's status.

    A row with no record is still a dash. Features that ran before this field
    existed have `fixes` and no `fix_status`, and guessing backwards from how
    the stage finally ended would invent a history nobody observed.
    """
    words = ((s.get("regression") or {}).get(stage) or {}).get("fix_status") or ""
    words = words.split()
    return words[number - 1] if number <= len(words) else "—"


COMMENTS_ICON = "\U0001F4AC"
ROUNDS_ICON = "\U0001F501"

# Every session the feature ran, one row each, in the order they began: the
# rows are gathered kind by kind below and sorted once at the end, so a
# friction review sits right after the session it read and a demo refresh
# after the merge it followed. A step not reached yet goes last, in the
# cycle's order (one rewound past keeps its old start, shown, and sorts by
# it); any other row with no start of its own stays beside the row
# gathered before it.
rows = []
LATER = datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)


def moment(value):
    """A recorded time as a comparable moment; None when there is none.
    A time without an offset is the machine's own."""
    try:
        at = datetime.datetime.fromisoformat(value or "")
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo else at.astimezone()


def add(started, text, later=False):
    at = LATER if later else moment(started)
    if at is None:
        before = [r[0] for r in rows if r[0] != LATER]
        at = before[-1] if before else datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    rows.append((at, len(rows), text))


def part_word(run):
    """Which part of a feature built in parts (parts.sh) a session worked on,
    as session_runs recorded it: a part's number, or `whole` while the whole
    is checked and after the last part is in."""
    part = run.get("part")
    if not part:
        return ""
    return " · the whole" if part == "whole" else " · part %s" % part


for name in ORDER:
    node = steps.get(name) or {}
    session = node.get("session")
    if node.get("done"):
        status = "done"
    elif name == current:
        status = "in progress"
    elif session:
        status = "interrupted"
    else:
        status = "—"
    # One row per conversation the step ran in (step_run, steps.sh). A step
    # re-entered in the same conversation is one row spanning its first start
    # and last exit; a new conversation is a row of its own, numbered. The
    # step's status and friction review belong to its last row; an earlier one
    # either closed the step on a pass since reopened, or was left behind.
    runs = [r for r in (node.get("runs") or []) if isinstance(r, dict)]
    if not runs:
        # A feature from before `runs`, or a step that opened no session (a
        # clean review): the step's own fields, as they always were.
        add(node.get("started"), "| %s | %s | %s | %s | %s | %s |" % (
            TITLES[name],
            status,
            "`%s`" % session[:8] if session else "—",
            when(node.get("started")),
            when(node.get("finished")),
            friction_cell(name),
        ), later=status == "—" and not node.get("started") and current in ORDER
           and ORDER.index(name) > ORDER.index(current))
        continue
    # The friction review follows every session (session_ended), keyed
    # `<step>-<n>` by the session's row — so each row has its own cell. A
    # feature from before that keyed it by the step alone, reviewed at the
    # step's close: that review sits on the last row, and the rows above it
    # had none of their own.
    per_run = any(("%s-%d" % (name, n)) in reviews for n in range(1, len(runs) + 1))
    for number, run in enumerate(runs, start=1):
        last = number == len(runs)
        sid = run.get("session") or ""
        if last:
            run_status = status
            # The later of the last exit and the step's closing: after_step
            # closes it once the session is gone, and a merge can close it
            # days later without one.
            ends = [run.get("finished")]
            if node.get("done"):
                ends.append(node.get("finished"))
            finished = max((e for e in ends if e), default=None)
        else:
            run_status = run.get("outcome") or ("done" if run.get("done") else "interrupted")
            finished = run.get("finished")
        # What the automatic review handed a review session (run_comments),
        # and how many of its rounds the session worked (run_rounds). Icons
        # rather than words keep the Step column narrow. No legend under the
        # table: the person reading it asked for none.
        said = ""
        for field, icon in (("comments", COMMENTS_ICON), ("rounds", ROUNDS_ICON)):
            value = run.get(field)
            if isinstance(value, int):
                said += " - %d %s" % (value, icon)
        said = part_word(run) + said
        add(run.get("started"), "| %s | %s | %s | %s | %s | %s |" % (
            TITLES[name] + (" (%d)" % number if len(runs) > 1 else "") + said,
            run_status,
            "`%s`" % sid[:8] if sid else "—",
            when(run.get("started")),
            when(finished),
            run_friction_cell(name, number, last, run_status, per_run),
        ))

# The local review's passes, beneath the review's own sessions: each one is
# a conversation of its own (`claude -p`, local_review.sh), and a reader
# counting the feature's sessions should find them here as well. Read from
# the journal beside the state; a pass with no model run (a head with nothing
# open to check, `seconds` 0) is no session and has no row. A pass journaled
# before passes were named has a dash for its id. A pass that ran and was not
# recorded (`spent` in local_review.py: stopped, or its answer not taken) is
# a session all the same, marked so: it reviewed nothing.
def review_pass_rows():
    path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])),
                        "review-rounds.jsonl")
    passes = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and int(row.get("seconds") or 0) > 0 \
                        and row.get("source") != "github":
                    passes.append(row)
    except OSError:
        return
    for number, row in enumerate(passes, start=1):
        sid = row.get("session") or ""
        began = ended = ""
        # The journal is in UTC, the state in the machine's own time, and
        # when() reads the clock off the string: the pass is put in local time
        # first, or it reads hours apart from the step it reviewed.
        try:
            start = datetime.datetime.fromisoformat(row.get("at") or "").astimezone()
            began = start.isoformat()
            ended = (start + datetime.timedelta(seconds=int(row["seconds"]))).isoformat()
        except (ValueError, TypeError):
            pass
        found = row.get("new")
        add(began, "| %s%s%s | %s | %s | %s | %s | — |" % (
            "local review",
            " (%d)" % number if len(passes) > 1 else "",
            " - %d %s" % (found, COMMENTS_ICON) if isinstance(found, int) else "",
            "stopped, not recorded" if row.get("spent") else "done",
            "`%s`" % sid[:8] if sid else "—",
            when(began),
            when(ended),
        ))


review_pass_rows()

# The fixing sessions, as rows of their own beneath the steps.
#
# In the same table rather than a second one: they are part of the same story,
# and a reader following a feature top to bottom should not have to find where
# the second table starts.
#
# Status used to be a dash here, on the reasoning that a fixing session has no
# step status to report. That much is still true — it has no `done` in `steps`,
# and the step words do not apply to it — but it was the wrong question. A
# fixing session has an outcome, regression_gate knows it exactly at the moment
# it happens, and the dash threw it away: a stage with four of them showed four
# identical cells, one of which had made it green.
#
# The times are the session's own, from fix_started and fix_finished, which
# regression_fix writes aligned with `fixes`. Features that ran before those
# fields existed fall back to the friction review's times, which is all they
# recorded; a row with neither carries dashes and still earns its place — it
# says the session happened.
STAGE_ORDER = ("local", "preview", "prod")
for stage in STAGE_ORDER:
    ids = ((s.get("regression") or {}).get(stage) or {}).get("fixes") or ""
    stage_node = (s.get("regression") or {}).get(stage) or {}
    starts = (stage_node.get("fix_started") or "").split()
    ends = (stage_node.get("fix_finished") or "").split()
    for number, short in enumerate(ids.split(), start=1):
        key = "fix-%s-%d" % (stage, number)
        node = reviews.get(key) if isinstance(reviews.get(key), dict) else {}
        if number <= len(starts) and starts[number - 1] != "-":
            end = ends[number - 1] if number <= len(ends) else ""
            node = {"started": starts[number - 1],
                    "finished": "" if end == "-" else end}
        add(node.get("started"), "| %s (%d) | %s | `%s` | %s | %s | %s |" % (
            fix_name(stage),
            number,
            fix_status_cell(stage, number),
            short,
            when(node.get("started")),
            when(node.get("finished")),
            friction_cell(key),
        ))

# The sessions after the steps, a row for each conversation like every other
# session the orchestrator starts, numbered when a kind ran more than once.
# A sync's friction review is keyed by its run's number (sync-N, sync.sh); the
# epilogue and the retrospective have none.
def run_rows(node, name, friction=False):
    runs = [r for r in ((s.get(node) or {}).get("runs") or []) if isinstance(r, dict)]
    # A name that depends on the run (a demo: a part's or a refresh) is
    # counted among the runs of its own name and part — a part's number is
    # said beside it already (part_word). A fixed name keeps its position,
    # which its friction review's title (`sync-<n>`) names it by too.
    keys = [(name(r), part_word(r)) for r in runs] if callable(name) else []
    for number, run in enumerate(runs, start=1):
        if keys:
            label, key = keys[number - 1][0], keys[number - 1]
            same, nth = keys.count(key), keys[:number].count(key)
        else:
            label, same, nth = name, len(runs), number
        sid = run.get("session") or ""
        # Running only when the caller says so: run_retro writes the summary
        # as the retrospective starts (SCLAUDE_SUMMARY_RUNNING). Read from the
        # runs, a resumed conversation keeps its earlier end and one cut off
        # keeps no end at all, and neither says whether it runs now.
        # Before `done`: a resumed run keeps the mark of its earlier close.
        if number == len(runs) and os.environ.get("SCLAUDE_SUMMARY_RUNNING") == node:
            word = "in progress"
        elif run.get("done"):
            word = "done"
        else:
            # A reason the orchestrator gave at its end (a demo refresh's
            # exit code), or none: left behind.
            word = run.get("outcome") or "interrupted"
        add(run.get("started"), "| %s%s%s | %s | %s | %s | %s | %s |" % (
            label,
            " (%d)" % nth if same > 1 else "",
            part_word(run),
            word,
            "`%s`" % sid[:8] if sid else "—",
            when(run.get("started")),
            when(run.get("finished")),
            friction_cell("%s-%d" % (node, number)) if friction else "—",
        ))
    return runs


# The syncs with main (sync.sh): one each time the reviewed branch stopped
# merging with main. The epilogues, which rewrite the status section in the
# issue and its parents: several in a feature's life — after the preview,
# after production. And the retrospective before the clean-up (retro.sh),
# the last one.
sync_runs = run_rows("sync", "sync with main", friction=True)
epilogue_runs = run_rows("epilogue", "status update")
retro_runs = run_rows("retro", "retrospective")
# The demo recorded again once the code moved past it (demo_refresh, demo.sh):
# a `claude -p` of its own before QA and at the epilogue; or a part's own demo,
# recorded between the parts (demo_part), which its run's `about` names.
run_rows("demo", state_file.demo_name)


def friction_subject(key):
    """The session a friction review read, named as its own row is: `code-1`
    is development — development (1) when the step ran in more than one
    conversation — `fix-local-2` the second fix after regression, `sync-1`
    the sync with main. A key from before per-session keys is the step's
    name alone."""
    if key.startswith("fix-"):
        stage, _, number = key[4:].rpartition("-")
        return "%s (%s)" % (fix_name(stage), number) if stage else key
    name, _, number = key.rpartition("-")
    if not number.isdigit():
        name, number = key, ""
    title = TITLES.get(name) or {"sync": "sync with main"}.get(name, name)
    node = steps.get(name) if name in TITLES else s.get(name)
    many = len((node or {}).get("runs") or []) > 1 if isinstance(node, dict) else False
    return "%s (%s)" % (title, number) if number and many else title


# The friction reviews' own conversations, each a row like any other session:
# the Friction column says what a session's review came to, this row when it
# ran. A log of proposals alone is put off without a session
# (friction_defer_proposals): a row with no id, timed by the put-off's
# commit. The `claude -p` call that may match them to the rules put off
# before (friction_classify.py, kept by nobody, made only when there is
# anything to match them to) runs just before it and has no row of its own.
# An empty log called nothing and has none.
for key, node in reviews.items():
    if not isinstance(node, dict):
        continue
    runs = [r for r in (node.get("runs") or []) if isinstance(r, dict)]
    for number, run in enumerate(runs, start=1):
        sid = run.get("session") or ""
        if not sid:
            continue
        if sid.startswith("deferred-"):
            add(run.get("started"), "| friction put off - %s%s%s | %s | — | %s | %s | — |" % (
                friction_subject(key),
                " (%d)" % number if len(runs) > 1 else "",
                part_word(run),
                "put off" if run.get("done") else "interrupted",
                when(run.get("started")),
                when(run.get("finished")),
            ))
            continue
        last = number == len(runs)
        if run.get("stalled"):
            word = "stalled"
        elif run.get("done"):
            word = run.get("outcome") or "reviewed"
        elif last and node.get("session") == sid and not node.get("done"):
            # As the Friction column says it: holding the cycle until it is
            # resumed or closed.
            word = "open"
        else:
            word = "interrupted"
        add(run.get("started"), "| friction review - %s%s%s | %s | `%s` | %s | %s | — |" % (
            friction_subject(key),
            " (%d)" % number if len(runs) > 1 else "",
            part_word(run),
            word,
            sid[:8],
            when(run.get("started")),
            when(run.get("finished")),
        ))

# The cycle counts seven steps, as the menu does (step_label and
# cycle_number in steps.sh): the four of ORDER, then the sync with main, the
# epilogue and the retrospective. Past step 4 the state says `done`, and what
# follows is read from the runs above. Unlike the menu this asks GitHub
# nothing, so a merge it cannot see leaves the feature at "4/7 done" until
# the retrospective.
TOTAL = int(os.environ.get("SCLAUDE_TOTAL") or len(ORDER) + 3)
if current == "done":
    # A running retrospective first: resumed, its run is marked done already.
    if retro_runs and os.environ.get("SCLAUDE_SUMMARY_RUNNING") == "retro":
        head = "step %d/%d retro" % (TOTAL, TOTAL)
    elif s.get("no_change") or s.get("cleaned") or (retro_runs and retro_runs[-1].get("done")):
        head = "all done"
    elif retro_runs:
        head = "step %d/%d retro" % (TOTAL, TOTAL)
    # A sync left open does not outlive the merge: remind_prod closes it
    # there, before the epilogue that writes this.
    elif sync_runs and not sync_runs[-1].get("done"):
        head = "step %d/%d sync" % (len(ORDER) + 1, TOTAL)
    else:
        head = "step %d/%d done" % (len(ORDER), TOTAL)
else:
    index = ORDER.index(current) + 1 if current in ORDER else 0
    head = "step %d/%d %s" % (index, TOTAL, TITLES.get(current, current))

# The heading names the kind of comment and nothing of the feature, so that
# it is found the same way on every issue; the feature and its step follow.
out = [
    "<!-- sclaude:%s -->" % slug,
    "## Sessions and progress",
    "",
    "Feature `%s` · %s" % (slug, head),
    "",
    "| Step | Status | Session | Started | Finished | Friction |",
    "|---|---|---|---|---|---|",
    *[text for _, _, text in sorted(rows)],
    "",
]

line = "Branch `%s`" % s.get("branch", "")
if s.get("pr"):
    line += " · PR #%s" % s["pr"]
elif s.get("no_change"):
    # no_change.sh: the cycle ended at step 2, and the empty rows above are
    # steps it had no reason to take rather than steps it has not reached.
    line += " · no change to the code: no pull request, review, preview or production"
out.append(line)

wt = s.get("worktree") or ""
out.append("Worktree `%s`%s" % (
    wt.rsplit("/", 1)[-1],
    " — removed" if s.get("cleaned") else "",
))

# The regression, and what it cost.
#
# Two lines rather than columns in the table above: a stage is not a step. The
# table's rows are the cycle's four steps, and a reader who found "preview red
# on e2e" wedged into one of them would reasonably conclude the step itself had
# failed. These stand underneath, where they read as what they are — what the
# machine checked, and what it had to do about it.
#
# Absent entirely when nothing has run: a feature that never reached a
# regression should not carry a line saying so.
STAGES = ("local", "preview", "prod")
regression = s.get("regression") or {}
verdicts = []
for stage in STAGES:
    node = regression.get(stage) or {}
    status = node.get("status")
    if not status:
        continue
    if status == "passed":
        verdicts.append("%s green" % stage)
    elif status == "failed":
        where = node.get("failed_at")
        verdicts.append("%s red%s" % (stage, " on `%s`" % where if where else ""))
    elif status == "running":
        verdicts.append("%s running" % stage)
if verdicts:
    out.append("Regression: %s" % ", ".join(verdicts))

# A step that went into the background, which by design cannot happen.
#
# sclaude refuses to start a step without a terminal now, so nothing writes this
# field any more. It is still read: features started by an earlier sclaude carry
# it, and their summaries should say what happened rather than leave the reader
# to wonder why the cycle stopped moving. A backgrounded step never reaches
# after_step, so it got no next step and no friction review.
backgrounded = [TITLES.get(name, name) for name in ORDER
                if (steps.get(name) or {}).get("bg")]
if backgrounded:
    out.append(
        "⚠ Ran in the background: %s. By design there are no background runs —"
        " a step with no terminal is now refused rather than detached. This one"
        " predates that, and the cycle stopped after it: no next step and no"
        " friction review were started."
        % ", ".join(backgrounded))

# The address the preview regression was aimed at. A reader of the issue can
# open the deployment QA is looking at without going to find it.
preview_url = (regression.get("preview") or {}).get("url")
if preview_url:
    out.append("Preview: %s" % preview_url)

# What the friction reviews changed in the orchestrator.
#
# A second table rather than more columns in the first: these rows are not the
# feature's steps. One review can produce several commits, and a step that met
# no friction produces none — neither shape fits a row-per-step table, and
# wedging them in would make the first table lie about what a row is.
#
# Only reviews that committed appear. A review that read the entries and found
# every ban deliberate is a proper outcome and is already reported in the
# Friction column above; repeating it here as an empty row would say nothing.
# When no review changed anything the whole section is absent.
#
# The subjects come from `git log` in sclaude's checkout, gathered by issue_sync —
# see the comment there. Conventional Commits already name the kind of change,
# so the subject is printed as it stands rather than parsed into a verdict.
def fix_label(key):
    """The step or fixing session a review belonged to, as a reader knows it."""
    if key.startswith("fix-"):
        rest = key[4:]
        stage, _, number = rest.rpartition("-")
        return "%s (%s)" % (fix_name(stage), number) if stage else rest
    # A step session's review, `review-3`: named as its row in the first table.
    step, _, number = key.rpartition("-")
    if step in TITLES and number.isdigit():
        return "%s (%s)" % (TITLES[step], number)
    return TITLES.get(key, key)


fix_rows = []
for line in os.environ.get("SCLAUDE_FIXES", "").splitlines():
    key, tab, rest = line.partition("\t")
    if not tab:
        continue
    sha, tab, rest = rest.partition("\t")
    if not tab:
        continue
    subject, _, files = rest.partition("\t")
    fix_rows.append((key, sha, subject, files.split()))


# The verdict of one row. The review gives one for all of its work, and when it
# is a single kind every row carries it: the review read the entries and the
# commits do not say more than it did. `mixed` is the one word that tells a
# reader nothing about any particular row, so there each commit is judged by
# what it touched — known-denials.txt alone is a ban confirmed, anything else
# changed the orchestrator. Putting entries off commits nothing (the deferred
# file is local state, deferred.sh), so a `mixed` review with no commit lifted
# nothing: what is left of it is both of the other kinds.
KNOWN_PATH = "sclaude/known-denials.txt"


def row_verdict(verdict, sha, files):
    if verdict != "mixed":
        return [verdict] if verdict else []
    if not sha:
        return ["deliberate", "deferred"]
    if any(f != KNOWN_PATH for f in files):
        return ["lifted"]
    if KNOWN_PATH in files:
        return ["deliberate"]
    # A commit whose paths were not read back says nothing either way; the
    # review's own word is then all there is.
    return ["mixed"]


if fix_rows:
    out += [
        "",
        "**What the friction reviews changed**",
        "",
        "| Step | Verdict | Commit | Change |",
        "|---|---|---|---|",
    ]
    # Every row names its step and its verdict, even when the row above had
    # the same: a reader scanning one row should not have to look up the table
    # to learn whose commit it is, and a verdict per review rather than per
    # commit is what made `mixed` necessary at all.
    for key, sha, subject, files in fix_rows:
        node = reviews.get(key) if isinstance(reviews.get(key), dict) else {}
        kinds = row_verdict(node.get("verdict") or "", sha, files)
        # A row with no commit is a review that changed nothing on purpose. Its
        # Change cell carries the verdict's own note, which is the only account
        # of it there is; a commit's row keeps the subject.
        if sha:
            change = subject.replace("|", "\\|")
        else:
            change = (node.get("verdict_note") or "").replace("|", "\\|")
        out.append("| %s | %s | %s | %s |" % (
            fix_label(key),
            " ".join("`%s`" % k for k in kinds) or "—",
            "`%s`" % sha if sha else "—",
            change,
        ))

out += [
    "",
    "<sub>Written by <code>sclaude</code>. Session ids resume with "
    "<code>claude --resume &lt;id&gt;</code> on the machine that ran them.</sub>",
]
print("\n".join(out))
PY
)" || return 0
  [[ -n "$body" ]] || return 0

  # Our own comment by its marker. gh has its own jq here, no external one is
  # required.
  id="$(gh api "repos/$repo/issues/$issue/comments" --paginate \
        --jq "map(select(.body | startswith(\"<!-- sclaude:$(state_get "$state" feature) -->\"))) | .[0].id" \
        2>/dev/null)" || id=""

  if [[ -n "$id" && "$id" != "null" ]]; then
    gh api --silent -X PATCH "repos/$repo/issues/comments/$id" \
      -f body="$body" >/dev/null 2>&1 \
      || warn "  could not update the summary on issue #$issue"
  else
    gh api --silent -X POST "repos/$repo/issues/$issue/comments" \
      -f body="$body" >/dev/null 2>&1 \
      || warn "  could not comment on issue #$issue"
  fi
  return 0
}
