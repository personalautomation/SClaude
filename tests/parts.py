#!/usr/bin/env python3
#
# A feature built in parts (parts.sh, plan_parts.py): one issue, one plan,
# one pull request, one QA; the parts built one after another, the whole
# accepted, then the parts made one branch.
#
# Guarded here, with git real (a bare origin in a temporary directory) and gh
# faked:
#
#   * the plan's `## Parts` is read, and a criterion's `[part n]`; a plan
#     with one part, parts out of order, or a section quoted in a fence is
#     not split; each part's prompt gets its own criteria and the feature's;
#   * parts_capture puts the parts into the state, and parts_enter puts the
#     tree on the part — made off the part before it while building, the last
#     part for the whole; work done on the common branch before the split
#     becomes part 1, the common branch put back where it left main; never
#     over uncommitted work;
#   * parts_built goes on to the next part, and after the last to the whole;
#   * parts_join moves the feature's branch to the last part and keeps each
#     part's range; where that branch took commits of its own (main synced
#     there) it is merged into the last part first, a conflict to the sync
#     session; parts_merge_in undoes a merge that conflicts and hands it to
#     the sync session;
#   * `sclaude parts <name> stop` while building checks the whole on the last
#     part kept, and is refused once the whole is accepted;
#   * the local review's journal and its waiting findings are kept per pull
#     request;
#   * the menu says which part, and the prompts say what a part and a review
#     block are.
#
# Run it with: python3 tests/parts.py
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
sys.path.insert(0, LIB)
import _path  # noqa: E402,F401
import acceptance  # noqa: E402
import plan_parts  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main"]


def git(*args, cwd=None):
    done = subprocess.run(GIT + list(args), cwd=cwd, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), done.stderr.strip()))
    return done.stdout.strip()


def run_bash(script, cwd, bin_dir, extra=""):
    body = "set -uo pipefail\n"
    body += 'BOLD=""; OFF=""; GREEN=""; REPO=%s; LIB=%s; SELF=sclaude\n' % (cwd, LIB)
    for name in ("core/io", "core/ui", "core/steps", "core/state", "tree/branches",
                 "tree/sync", "tree/parts", "core/cycle_steps", "review/review_blocks"):
        body += 'source "%s/%s.sh"\n' % (LIB, name)
    body += ('info() { echo "INFO $*"; }; warn() { echo "WARN $*"; }\n'
             'ask_feed() { :; }; issue_sync() { echo SYNC; }\n'
             'run_step() { echo "RUN_STEP $3"; }\n'
             'sync_branch() { echo SYNC_BRANCH; return 0; }\n'
             'merge_method() { echo --squash; }\n'
             'worktree_dirt() { git -C "$1" status --porcelain; }\n'
             'merge_under_way() { [[ -f "$1/.git/MERGE_HEAD" ]]; }\n')
    body += extra + script
    env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"],
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    out = subprocess.run(["bash", "-c", body], cwd=cwd, capture_output=True,
                         text=True, env=env, timeout=60)
    return out.stdout + out.stderr, out.returncode


# --- the plan --------------------------------------------------------------------
PLAN = """# Tickets

## Acceptance criteria

- [ ] AC1. [part 1] A person can take part.
- [ ] AC2. **[part 2]** The tickets page lists tickets.
- [ ] AC3. Nothing breaks.

## Parts

### Part 1 — Participation
The table and the panel.

### Part 2: Tickets page
The page.

## Data model
"""
check("parts-read", plan_parts.plan_parts(PLAN), [(1, "Participation"), (2, "Tickets page")])
check("a-space-after-the-number-is-a-heading",
      plan_parts.plan_parts("## Parts\n### Part 1 — A\n### Part 2 Tickets page\n"), [(1, "A"), (2, "Tickets page")])
check("one-part-is-no-split",
      plan_parts.plan_parts("## Parts\n\n### Part 1 — All\n"), [])
check("out-of-order-is-no-split",
      plan_parts.plan_parts("## Parts\n\n### Part 1 — A\n### Part 3 — C\n"), [])
check("a-deeper-part-heading-is-the-parts-text",
      plan_parts.plan_parts("## Parts\n### Part 1 — A\n#### Part 1 notes\n### Part 2 — B\n"), [(1, "A"), (2, "B")])
check("a-fenced-section-is-no-split",
      plan_parts.plan_parts("```\n## Parts\n### Part 1 — A\n### Part 2 — B\n```\n"), [])
check("the-section-ends-at-the-next-heading",
      plan_parts.plan_parts(PLAN + "\n### Part 3 — not a part\n"),
      [(1, "Participation"), (2, "Tickets page")])
found = acceptance.plan_criteria(acceptance.plan_section(PLAN))
check("criterion-part", [plan_parts.criterion_part(t) for _, t in found], [1, 2, None])
check("an-older-pr-mark-reads-as-a-part", plan_parts.criterion_part("[PR 3] Pushes."), 3)
check("a-part-keeps-its-own-and-the-features",
      [c for c, _ in plan_parts.of_part(found, 2)], ["AC2", "AC3"])

# The prompt's block for a part, from the issue's list.
issue_body = acceptance.AC_OPEN + "\n" + "\n".join(
    acceptance.criterion_line(c, t) for c, t in found) + "\n" + acceptance.AC_CLOSE
acceptance.fetch_text = lambda number, cwd=None: issue_body
block = acceptance.render(41, part=1)
check("part-block-has-its-criteria", "**AC1.**" in block and "**AC3.**" in block, True)
check("part-block-leaves-the-others-out", "**AC2.**" in block, False)
check("part-block-says-whose", "Part 1's criteria" in block, True)
check("whole-block-has-all", "**AC2.**" in acceptance.render(41), True)

# --- the shell side ----------------------------------------------------------------
tmp = tempfile.mkdtemp()
try:
    origin = os.path.join(tmp, "origin.git")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    wt = os.path.join(tmp, "wt")
    subprocess.run(GIT + ["clone", "-q", origin, wt], check=True, capture_output=True)
    git("commit", "-q", "--allow-empty", "-m", "main", cwd=wt)
    git("push", "-q", "origin", "HEAD:main", cwd=wt)
    git("switch", "-q", "-c", "feat/t", cwd=wt)
    base = git("rev-parse", "HEAD", cwd=wt)
    fdir = os.path.join(wt, ".sclaude", "local", "feature")
    os.makedirs(fdir)
    with open(os.path.join(wt, ".git", "info", "exclude"), "a") as fh:
        fh.write(".sclaude/\n")
    with open(os.path.join(fdir, "plan.md"), "w") as fh:
        fh.write(PLAN)
    spath = os.path.join(fdir, "state.json")

    def write_state(data):
        with open(spath, "w") as fh:
            json.dump(data, fh)

    def read_state():
        with open(spath) as fh:
            return json.load(fh)

    write_state({"feature": "t", "branch": "feat/t", "issue": 41, "step": "code",
                 "steps": {"plan": {"done": True},
                           "code": {"session": "c1", "runs": [{"session": "c1"}]}}})

    bin_dir = os.path.join(tmp, "bin")
    os.makedirs(bin_dir)
    # gh, from a JSON file of pull requests the test writes: `pr view <n>
    # --json …` answers with its record; `pr merge <n>` squashes its branch
    # into its base on origin; `pr ready` and `pr list` are recorded.
    prs_file = os.path.join(tmp, "prs.json")
    with open(os.path.join(bin_dir, "gh"), "w") as fh:
        fh.write(r'''#!/usr/bin/env bash
echo "$*" >> "%(log)s"
prs="%(prs)s"
case "$1 $2" in
  "pr view")
    python3 - "$prs" "$3" "$@" <<'PY'
import json, sys
prs = json.load(open(sys.argv[1]))
rec = prs.get(sys.argv[2])
if rec is None:
    sys.exit(1)
if "--jq" in sys.argv:
    print(rec.get(sys.argv[sys.argv.index("--jq") + 1].lstrip("."), ""))
    sys.exit(0)
print(json.dumps(rec))
PY
    ;;
  "pr merge")
    rec="$(python3 -c 'import json,sys; r=json.load(open(sys.argv[1]))[sys.argv[2]]; print(r["headRefName"], r["baseRefName"])' "$prs" "$3")"
    read -r head base <<< "$rec"
    tmpc="$(mktemp -d)"
    git clone -q "%(origin)s" "$tmpc/c" && cd "$tmpc/c" \
      && git switch -q "$base" && git merge -q --squash "origin/$head" \
      && git -c user.name=t -c user.email=t@t commit -q -m "squash $head" \
      && git push -q origin "$base" || exit 1
    python3 - "$prs" "$3" <<'PY'
import json, sys
prs = json.load(open(sys.argv[1])); prs[sys.argv[2]]["state"] = "MERGED"
json.dump(prs, open(sys.argv[1], "w"))
PY
    ;;
  "pr list") echo "" ;;
  *) : ;;
esac
''' % {"log": os.path.join(tmp, "gh.log"), "prs": prs_file, "origin": origin})
    os.chmod(os.path.join(bin_dir, "gh"), 0o755)
    with open(prs_file, "w") as fh:
        json.dump({}, fh)

    # parts_capture
    out, rc = run_bash('parts_capture "%s"' % wt, wt, bin_dir)
    st = read_state()
    check("capture-total", st.get("parts", {}).get("total"), 2)
    check("capture-umbrella", st["parts"].get("umbrella"), "feat/t")
    check("capture-current", st["parts"].get("current"), 1)
    check("capture-titles", st["parts"].get("2", {}).get("title"), "Tickets page")

    # A feature already with its pull request is not split under it.
    st = read_state(); saved = json.loads(json.dumps(st))
    st.pop("parts"); st["pr"] = 77; write_state(st)
    with open(prs_file, "w") as fh:
        json.dump({"77": {"state": "OPEN"}}, fh)
    out, rc = run_bash('parts_capture "%s"' % wt, wt, bin_dir)
    check("not-split-with-a-pr-open", "parts" in read_state(), False)
    check("not-split-with-a-pr-open-says-so", "stays one pull request" in out, True)
    write_state(saved)

    # parts_enter adopts the work made on the common branch before the split.
    with open(os.path.join(wt, "a.txt"), "w") as fh:
        fh.write("part one\n")
    git("add", "a.txt", cwd=wt)
    git("commit", "-q", "-m", "part one work", cwd=wt)
    work = git("rev-parse", "HEAD", cwd=wt)
    with open(os.path.join(wt, "dirt.txt"), "w") as fh:
        fh.write("x")
    out, rc = run_bash('parts_enter "%s"' % wt, wt, bin_dir)
    check("not-over-uncommitted-work", rc, 1)
    check("tree-left-where-it-was", git("branch", "--show-current", cwd=wt), "feat/t")
    os.remove(os.path.join(wt, "dirt.txt"))
    out, rc = run_bash('parts_enter "%s"' % wt, wt, bin_dir)
    check("enter-ok", rc, 0)
    check("on-part-1", git("branch", "--show-current", cwd=wt), "feat/t-1")
    check("part-1-carries-the-work", git("rev-parse", "HEAD", cwd=wt), work)
    check("umbrella-back-where-it-left-main", git("rev-parse", "feat/t", cwd=wt), base)
    check("no-pull-request-base-pushed-while-building",
          bool(git("ls-remote", "--heads", "origin", "feat/t", cwd=wt)), False)
    # A replan that no longer splits, made with the tree on the common
    # branch: part 1's work comes back onto it all the same.
    saved = read_state()
    git("switch", "-q", "feat/t", cwd=wt)
    with open(os.path.join(fdir, "plan.md"), "w") as fh:
        fh.write("# Plan\n")
    out, rc = run_bash('parts_capture "%s"' % wt, wt, bin_dir)
    check("uncapture-from-the-common-branch",
          (rc, git("rev-parse", "feat/t", cwd=wt), "parts" in read_state() and read_state()["parts"] is not None,
           bool(git("branch", "--list", "feat/t-1", cwd=wt))), (0, work, False, False))
    git("switch", "-q", "-c", "feat/t-1", work, cwd=wt)
    git("branch", "-q", "-f", "feat/t", base, cwd=wt)
    with open(os.path.join(fdir, "plan.md"), "w") as fh:
        fh.write(PLAN)
    write_state(saved)
    st = read_state()
    check("state-branch-is-the-part", st.get("branch"), "feat/t-1")
    check("part-branch-recorded", st["parts"]["1"].get("branch"), "feat/t-1")
    out, rc = run_bash('step_label code "%s"' % wt, wt, bin_dir)
    check("label-says-the-part", out.strip(), "2/7 development · part 1/2")

    # Part 1 also adds a helper, which its review will delete.
    with open(os.path.join(wt, "helper.txt"), "w") as fh:
        fh.write("helper\n")
    git("add", "helper.txt", cwd=wt)
    git("commit", "-q", "-m", "part one helper", cwd=wt)

    # parts_built: the next part is built, no pull request between.
    st = read_state()
    st["steps"]["code"] = {"session": "c1", "done": True, "runs": [{"session": "c1"}]}
    write_state(st)
    out, rc = run_bash('parts_built "%s" t' % wt, wt, bin_dir)
    st = read_state()
    check("built-goes-to-the-next-part", (rc, st["parts"]["current"], st["step"], "RUN_STEP code" in out),
          (0, 2, "code", True))
    check("built-part-code-kept-and-afresh",
          (st["parts"]["1"]["steps"]["code"].get("session"), st["steps"]["code"]), ("c1", {"runs": [{"session": "c1"}]}))
    check("no-pull-request-asked-for", "pr create" in open(os.path.join(tmp, "gh.log")).read()
          if os.path.exists(os.path.join(tmp, "gh.log")) else False, False)

    # Part 2 made off part 1's branch.
    out, rc = run_bash('parts_enter "%s"' % wt, wt, bin_dir)
    check("enter-part-2", (rc, out if rc else ""), (0, ""))
    check("on-part-2", git("branch", "--show-current", cwd=wt), "feat/t-2")
    check("part-2-off-part-1", git("rev-parse", "HEAD", cwd=wt), git("rev-parse", "feat/t-1", cwd=wt))
    check("common-branch-still-where-it-left-main", git("rev-parse", "feat/t", cwd=wt), base)
    with open(os.path.join(wt, "b.txt"), "w") as fh:
        fh.write("part two\n")
    # Part 2 also builds on part 1's file — which part 1's review will change.
    with open(os.path.join(wt, "a.txt"), "a") as fh:
        fh.write("part two uses it\n")
    git("add", "b.txt", "a.txt", cwd=wt)
    git("commit", "-q", "-m", "part two work", cwd=wt)
    out, rc = run_bash('parts_built "%s" t' % wt, wt, bin_dir)
    st = read_state()
    check("last-part-built-the-whole-next",
          (st["parts"].get("built"), st["parts"]["current"], st["step"], "RUN_STEP code" in out), (True, 1, "code", True))
    out, rc = run_bash('parts_whole "%s" && echo whole; parts_enter "%s"; step_label code "%s"' % (spath, wt, wt), wt, bin_dir)
    check("the-whole-on-the-last-part", (out.splitlines()[0], git("branch", "--show-current", cwd=wt)),
          ("whole", "feat/t-2"))
    check("the-whole-has-a-plain-label", out.strip().splitlines()[-1], "2/7 development")

    # Accepted: the parts become one branch, the feature's, moved to the
    # last part (a fast-forward: the parts are stacked).
    tip1, tip2 = git("rev-parse", "feat/t-1", cwd=wt), git("rev-parse", "feat/t-2", cwd=wt)
    st = read_state(); st["parts"]["accepted"] = True; write_state(st)
    out, rc = run_bash('parts_joining "%s" && echo JOINING; parts_join "%s" t' % (spath, wt), wt, bin_dir)
    st = read_state()
    check("join-ok", (rc, "JOINING" in out, "RUN_STEP pr" in out), (0, True, True))
    check("joined-on-the-features-branch", (git("branch", "--show-current", cwd=wt), git("rev-parse", "feat/t", cwd=wt)),
          ("feat/t", tip2))
    check("joined-state", (st["parts"].get("done"), st.get("branch"), st.get("step")), (True, "feat/t", "pr"))
    check("joined-ranges", (st["parts"]["1"].get("range"), st["parts"]["2"].get("range")),
          ("%s..%s" % (base, tip1), "%s..%s" % (tip1, tip2)))
    check("joined-reads-from-main", (st.get("blocks") or {}).get("base"), None)
    out, rc = run_bash('parts_open "%s" || echo ONE; parts_joining "%s" || echo JOINED; step_label pr "%s"' % (spath, spath, wt),
                       wt, bin_dir)
    check("after-the-join-one-feature", (out.split()[:2], "part" in out.splitlines()[-1]), (["ONE", "JOINED"], False))
    out, rc = run_bash('parts_branches "%s"' % spath, wt, bin_dir)
    check("branches-for-the-clean-up", out.split(), ["feat/t-1", "feat/t-2"])
    joined = read_state()

    # The feature's branch took a commit of its own after the parts left it
    # (main synced there): it merges into the last part — the conflict to the
    # sync session, told to merge into and push the last part's branch, not
    # the feature's it merges in — and the review reads from main.
    git("switch", "-q", "-c", "lg", base, cwd=wt)
    git("switch", "-q", "-c", "lg-1", cwd=wt)
    with open(os.path.join(wt, "l.txt"), "w") as fh:
        fh.write("one\n")
    git("add", "l.txt", cwd=wt); git("commit", "-q", "-m", "lg part one", cwd=wt)
    old1 = git("rev-parse", "HEAD", cwd=wt)
    git("switch", "-q", "-c", "lg-2", cwd=wt)
    with open(os.path.join(wt, "l.txt"), "a") as fh:
        fh.write("two uses it\n")
    git("add", "l.txt", cwd=wt); git("commit", "-q", "-m", "lg part two", cwd=wt)
    lg2 = git("rev-parse", "HEAD", cwd=wt)
    git("switch", "-q", "lg", cwd=wt)
    with open(os.path.join(wt, "l.txt"), "w") as fh:
        fh.write("one, from main\n")
    git("add", "l.txt", cwd=wt); git("commit", "-q", "-m", "main synced", cwd=wt)
    git("push", "-q", "origin", "lg", cwd=wt)
    synced = git("rev-parse", "HEAD", cwd=wt)
    git("switch", "-q", "lg-1", cwd=wt)
    write_state({"feature": "t", "branch": "lg-1", "issue": 41, "step": "code",
                 "steps": {"code": {"session": "cw", "done": True}},
                 "parts": {"total": 2, "umbrella": "lg", "current": 1, "built": True, "accepted": True,
                           "1": {"branch": "lg-1"}, "2": {"branch": "lg-2"}}})
    sync_stub = ('sync_with_main() { echo "SYNC_FROM=$SYNC_FROM"; '
                 'echo "SYNC_INTO=$(state_get "$1/.sclaude/local/feature/state.json" branch)"; '
                 'git -C "$1" merge -q -X theirs --no-edit "$(sync_source)" >/dev/null 2>&1; return 3; }\n')
    out, rc = run_bash('parts_join "%s" t' % wt, wt, bin_dir, sync_stub)
    st = read_state()
    check("synced-join-ok", (rc, "SYNC_FROM=lg" in out, "RUN_STEP pr" in out), (0, True, True))
    check("synced-sync-merges-into-the-last-part", "SYNC_INTO=lg-2" in out, True)
    check("synced-joined-carries-both",
          [subprocess.run(["git", "merge-base", "--is-ancestor", c, "lg"], cwd=wt).returncode for c in (synced, lg2)],
          [0, 0])
    check("synced-ranges", (st["parts"]["1"].get("range"), st["parts"]["2"].get("range")),
          ("%s..%s" % (base, old1), "%s..%s" % (old1, lg2)))
    check("synced-reads-from-main", (st.get("blocks") or {}).get("base"), None)
    check("synced-on-the-features-branch", (git("branch", "--show-current", cwd=wt), st.get("branch")), ("lg", "lg"))
    write_state(joined)
    git("switch", "-q", "feat/t", cwd=wt)

    # A part whose branch does not take the common branch in cleanly: the
    # merge is undone, and the part waits.
    git("switch", "-q", "-c", "x-u", base, cwd=wt)
    with open(os.path.join(wt, "c.txt"), "w") as fh:
        fh.write("fixed in review\n")
    git("add", "c.txt", cwd=wt)
    git("commit", "-q", "-m", "review fix", cwd=wt)
    git("switch", "-q", "-c", "x-p", base, cwd=wt)
    with open(os.path.join(wt, "c.txt"), "w") as fh:
        fh.write("built on\n")
    git("add", "c.txt", cwd=wt)
    git("commit", "-q", "-m", "part work", cwd=wt)
    nosync = 'sync_with_main() { return 1; }\n'
    out, rc = run_bash('parts_merge_in "%s" t x-p x-u ""' % wt, wt, bin_dir, nosync)
    check("a-conflict-unresolved-holds-the-part", (rc, os.path.exists(os.path.join(wt, ".git", "MERGE_HEAD"))),
          (1, False))
    check("a-conflict-leaves-the-branch", git("log", "-1", "--format=%s", cwd=wt), "part work")
    # With the common branch on origin, the conflict goes to the sync session,
    # told to merge that branch (SYNC_FROM); its merge is what the part takes.
    git("push", "-q", "origin", "x-u", cwd=wt)
    sync_stub = ('sync_with_main() { echo "SYNC_FROM=$SYNC_FROM"; '
                 'git -C "$1" merge -q -X theirs --no-edit "origin/$SYNC_FROM" >/dev/null 2>&1; return 3; }\n')
    out, rc = run_bash('parts_merge_in "%s" t x-p x-u ""' % wt, wt, bin_dir, sync_stub)
    check("a-conflict-goes-to-the-sync-session", (rc, "SYNC_FROM=x-u" in out), (0, True))
    check("the-session-merge-is-taken",
          subprocess.run(["git", "merge-base", "--is-ancestor", "origin/x-u", "HEAD"], cwd=wt).returncode, 0)
    out, rc = run_bash('echo "FROM=$SYNC_FROM"', wt, bin_dir)
    check("sync-from-is-main-elsewhere", "FROM=main" in out, True)
    git("reset", "-q", "--hard", "HEAD~1", cwd=wt)
    stuck = 'sync_with_main() { return 1; }\n'
    out, rc = run_bash('parts_merge_in "%s" t x-p x-u ""' % wt, wt, bin_dir, stuck)
    check("a-sync-left-unfinished-holds-the-part", (rc, "waits" in out or rc == 1), (1, True))

    # `sclaude parts <name> stop`: ended with the parts built so far.
    st = read_state()
    st["parts"].update({"total": 3, "done": False, "current": 2, "built": False, "accepted": False})
    st["step"] = "code"; st["branch"] = "feat/t-2"; st["pr"] = None
    write_state(st)
    git("switch", "-q", "feat/t-2", cwd=wt)
    stubs = ('require_repo() { :; }; feature_worktree() { echo "%s"; }\n'
             'die() { echo "DIE $*"; exit 1; }\n'
             'ask() { printf -v "$2" y; }; is_yes() { [[ "$1" == y ]]; }\n' % wt)
    out, rc = run_bash('cmd_parts t stop', wt, bin_dir, stubs)
    stop_out = out
    st = read_state()
    check("stop-ok", (rc, out if rc else ""), (0, ""))
    check("stop-keeps-the-count-and-checks-the-whole",
          (st["parts"]["total"], st["parts"].get("built"), st["parts"]["current"]), (3, True, 1))
    check("stop-names-the-first-dropped", st["parts"].get("dropped"), 2)
    out, rc = run_bash('parts_last "%s"; parts_whole "%s" && echo whole' % (spath, spath), wt, bin_dir)
    check("after-a-stop-the-last-is-the-one-before", out.split(), ["1", "whole"])
    check("stop-closes-step-2-on-the-last-part-kept", (st["step"], st["branch"], "RUN_STEP code" in stop_out),
          ("code", "feat/t-1", True))
    check("stop-tree-on-the-last-part-kept", git("branch", "--show-current", cwd=wt), "feat/t-1")
    st["parts"].update({"built": False, "current": 1})
    st["parts"].pop("dropped", None)
    write_state(st)
    out, rc = run_bash('cmd_parts t stop', wt, bin_dir, stubs)
    check("nothing-to-ship-before-part-1-is-built", (rc, "nothing to ship" in out), (1, True))
    st["parts"].update({"built": True, "accepted": True, "current": 2})
    write_state(st)
    out, rc = run_bash('cmd_parts t stop', wt, bin_dir, stubs)
    check("no-stop-once-the-whole-is-accepted", (rc, "replan" in out), (1, True))

    # Every row of the history carries the part, and each new conversation.
    st["parts"].update({"done": False, "built": False, "accepted": False, "current": 2, "2": {"branch": "feat/t-2"}})
    st["parts"].pop("dropped", None)
    write_state(st)
    run_bash('history_add "%s" qa in; session_runs "%s" steps.code open s9' % (spath, spath), wt, bin_dir)
    with open(os.path.join(fdir, "history.jsonl")) as fh:
        last = json.loads(fh.read().splitlines()[-1])
    check("history-row-names-the-part",
          (last.get("part"), last.get("part_branch"), "part_pr" in last), ("2", "feat/t-2", False))
    check("a-run-names-the-part", read_state()["steps"]["code"]["runs"][-1].get("part"), "2")
    st = read_state(); st["parts"]["built"] = True; write_state(st)
    run_bash('history_add "%s" qa mid' % spath, wt, bin_dir)
    with open(os.path.join(fdir, "history.jsonl")) as fh:
        check("checking-the-whole-is-the-whole", json.loads(fh.read().splitlines()[-1]).get("part"), "whole")
    # Accepted, the parts not yet one branch: a sync session joining them is
    # the whole's, not part 1's (parts.current is back at 1 by then).
    st = read_state(); st["parts"].update({"accepted": True, "current": 1}); write_state(st)
    run_bash('history_add "%s" qa join' % spath, wt, bin_dir)
    with open(os.path.join(fdir, "history.jsonl")) as fh:
        check("joining-is-the-whole", json.loads(fh.read().splitlines()[-1]).get("part"), "whole")
    st = read_state(); st["parts"]["done"] = True; write_state(st)
    run_bash('history_add "%s" qa out' % spath, wt, bin_dir)
    with open(os.path.join(fdir, "history.jsonl")) as fh:
        check("after-the-parts-the-whole", json.loads(fh.read().splitlines()[-1]).get("part"), "whole")

finally:
    shutil.rmtree(tmp, ignore_errors=True)

# --- the local review's journal, per pull request ------------------------------------
tmp = tempfile.mkdtemp()
try:
    j = os.path.join(tmp, "review-rounds.jsonl")
    with open(j, "w") as fh:
        for row in ({"at": "2026-01-01T00:00:00+00:00", "head": "a1", "pr": "101"},
                    {"at": "2026-01-02T00:00:00+00:00", "head": "a2", "pr": "101"},
                    {"at": "2026-01-03T00:00:00+00:00", "head": "b1", "pr": "102"}):
            fh.write(json.dumps(row) + "\n")
    lr = os.path.join(LIB, "review", "local_review.py")

    def lrun(*args):
        return subprocess.run(["python3", lr] + list(args), capture_output=True, text=True)

    check("since-is-the-prs-own", lrun("since", j, "zz", "101").stdout.strip(), "a2")
    check("a-new-pr-starts-whole", lrun("since", j, "zz", "103").stdout.strip(), "")
    check("rounds-counted-per-pr", lrun("round", j, "zz", "102").stdout.strip(), "2")
    check("cached-per-pr", lrun("cached", j, "b1", "101").returncode, 1)
    check("cached-own", lrun("cached", j, "b1", "102").returncode, 0)
    check("null-pr-reads-all", lrun("since", j, "zz", "null").stdout.strip(), "b1")
    # Waiting findings stay with the pull request they were found on.
    sys.path.insert(0, os.path.join(LIB, "review"))
    import local_review  # noqa: E402
    waiting = [{"path": "a", "line": 1, "title": "x", "head": "h", "pr": "101"}]
    with open(local_review.unposted_file(j), "w") as fh:
        json.dump(waiting, fh)
    local_review.threads = lambda *a: []
    posted = []
    local_review.post = lambda cwd, pr, repo, head, f: posted.append(pr) or "thread"
    check("anothers-findings-not-posted", local_review.flush(tmp, "102", "o/r", j), (0, 0))
    check("anothers-findings-kept", local_review.pending_of(j), waiting)
    check("own-findings-posted", (local_review.flush(tmp, "101", "o/r", j), posted), ((1, 0), ["101"]))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# --- the prompts ------------------------------------------------------------------------
BASE_ENV = {"SCLAUDE_V_FEATURE": "t", "SCLAUDE_V_PR": "101", "SCLAUDE_V_ISSUE": "41",
            "SCLAUDE_V_DEV_URL": "u", "SCLAUDE_V_DEFERRED": "d", "SCLAUDE_V_DEV_PORT": "1",
            "SCLAUDE_V_MANUALS": "m", "SCLAUDE_V_DB_API": "", "SCLAUDE_V_SHARED_DB": "",
            "SCLAUDE_V_REVIEW_MODE": "local", "SCLAUDE_V_NO_REVIEW": "1",
            "SCLAUDE_V_REVIEW_LOCAL": "1", "SCLAUDE_V_DEMO": "1",
            "SCLAUDE_V_UMBRELLA": "feat/t", "SCLAUDE_V_PARTS": "3"}
IN_PART = dict(BASE_ENV, SCLAUDE_V_BASE="feat/t", SCLAUDE_V_PART="2", SCLAUDE_V_PART_TITLE="Tickets",
               SCLAUDE_V_PART_BASE="feat/t-1", SCLAUDE_V_IN_PARTS="1", SCLAUDE_V_PARTS_DONE="",
               SCLAUDE_V_PARTS_BUILT="", SCLAUDE_V_NOT_IN_PARTS="", SCLAUDE_V_ASKS_ACCEPT="",
               SCLAUDE_V_PART_ALONE="1", SCLAUDE_V_DEMO="")
# A look at each part (partAccept: each): the part ends on its demo and Accept.
EACH = dict(IN_PART, SCLAUDE_V_ASKS_ACCEPT="1", SCLAUDE_V_PART_ALONE="", SCLAUDE_V_DEMO="1")
WHOLE = dict(BASE_ENV, SCLAUDE_V_BASE="main", SCLAUDE_V_PART="", SCLAUDE_V_PART_TITLE="", SCLAUDE_V_PARTS_DROPPED="",
             SCLAUDE_V_IN_PARTS="", SCLAUDE_V_PARTS_DONE="", SCLAUDE_V_PARTS_BUILT="1", SCLAUDE_V_NOT_IN_PARTS="1",
             SCLAUDE_V_ASKS_ACCEPT="1", SCLAUDE_V_PART_ALONE="", SCLAUDE_V_PART_BASE="")
DONE = dict(WHOLE, SCLAUDE_V_PARTS_DONE="1", SCLAUDE_V_PARTS_BUILT="")


def render(step, env):
    done = subprocess.run(["python3", os.path.join(LIB, "cycle", "render_prompt.py"),
                           os.path.join(ROOT, "sclaude", "prompts", step + ".md"),
                           os.path.join(ROOT, "sclaude", "prompts")],
                          capture_output=True, text=True, env=dict(os.environ, **env))
    check("%s-renders" % step, (done.returncode, done.stderr[:200]), (0, ""))
    return done.stdout


code = render("code", IN_PART)
check("part-session-knows-its-part", "part 2 of 3: Tickets" in code, True)
check("part-session-not-asked-to-accept", "Accept work" in code, False)
check("part-session-ends-on-its-marker", "echo done > .sclaude/local/feature/session-done" in code, True)
check("part-session-read-with-fresh-eyes", "git diff feat/t-1...HEAD" in code and "three rounds at most" in code, True)
check("part-session-places-a-request", "you decide where it goes, not me" in code, True)
check("part-session-no-demo", "/sdemo" in code, False)
code = render("code", EACH)
check("a-look-at-each-part-asks", ("Accept work" in code, "/sdemo" in code, "to the next part" in code), (True, True, True))
check("a-look-at-each-part-no-marker-of-its-own", "starts the next part" in code, False)
code = render("code", WHOLE)
check("whole-feature-session-is-accepted", "Accept work" in code, True)
check("whole-feature-session-on-the-last-part", "the tree is on the last part's branch" in code, True)
check("nothing-dropped-nothing-said", "ended the parts early" in code, False)
dropped = render("code", dict(WHOLE, SCLAUDE_V_PARTS_DROPPED="2-3", SCLAUDE_V_ISSUE="41"))
check("dropped-parts-are-struck-and-filed",
      "parts 2-3" in dropped and "~~AC7. …~~" in dropped and "issues/41/sub_issues" in dropped, True)
code = render("code", DONE)
check("after-the-parts-a-plain-step-2", ("Accept work" in code, "built in parts" in code), (True, False))
SYNC = dict(BASE_ENV, SCLAUDE_V_BRANCH="feat/t-3", SCLAUDE_V_FROM="refs/remotes/origin/feat/t",
            SCLAUDE_V_FROM_PARTS="1", SCLAUDE_V_FROM_MAIN="", SCLAUDE_V_REVIEWED="", SCLAUDE_V_UNREVIEWED="",
            SCLAUDE_V_CONFLICTS="a.txt", SCLAUDE_V_UNFINISHED="", SCLAUDE_V_DB_API="", SCLAUDE_V_DB_CLI="npx --yes supabase")
sync = render("sync", SYNC)
check("parts-sync-is-the-join", ("one pull request into main" in sync, "each through a pull request" in sync,
                                 "`feat/t-3`, the branch this tree is on" in sync), (True, False, True))
check("parts-sync-no-database-none-said", "migration up" in sync, False)
sync = render("sync", dict(SYNC, SCLAUDE_V_DB_API="http://127.0.0.1:55001"))
check("parts-sync-names-the-features-database",
      ("`npx --yes supabase migration up`" in sync, "Don't pass `--workdir`" in sync), (True, True))
pr = render("pr", DONE)
check("feature-pr-closes-the-issue", "`Closes #41`" in pr, True)
check("feature-pr-lists-the-parts", ("Built in parts" in pr, "carries every part" in pr), (True, True))
check("feature-pr-no-part-pr", "gh pr create --base feat/t" in pr, False)
review = render("review", DONE)
check("feature-review-plain-without-blocks", ("read in blocks" in review, "For part" in review), (False, False))
BLOCK = dict(DONE, SCLAUDE_V_IN_BLOCKS="1", SCLAUDE_V_BLOCK="2", SCLAUDE_V_BLOCKS="4",
             SCLAUDE_V_BLOCK_TITLE="Taking a ticket")
review = render("review", BLOCK)
check("block-review-knows-its-block", "block 2 of 4: Taking a ticket" in review, True)
check("block-review-names-the-cut", ".sclaude/local/feature/review-blocks.json" in review, True)
plan = render("plan", dict(DONE, SCLAUDE_V_IN_PARTS=""))
check("plan-asks-for-the-parts-section", "`### Part <n> — <title>`" in plan, True)
check("plan-files-no-issue-for-a-part", "gh issue create" in plan, False)

# --- the cycle's code carries the hooks ---------------------------------------------------
with open(os.path.join(LIB, "cycle", "run.sh")) as fh:
    run_src = fh.read()
check("the-accepted-parts-are-joined", 'parts.accepted true\n    parts_join "$wt" "$slug"' in run_src, True)
check("a-part-built-goes-on", 'parts_building "$state"; then\n    parts_built' in run_src, True)
check("a-join-cut-off-goes-on", 'parts_joining "$state"; then\n      parts_join' in run_src, True)
check("a-review-block-closed-goes-on", 'blocks_next "$wt" "$slug"; then\n    run_step "$wt" "$slug" review' in run_src, True)
check("no-main-into-a-part", 'parts_open "$state" || { sync_branch' in run_src, True)
with open(os.path.join(LIB, "commands", "feature_commands.sh")) as fh:
    check("sclaude-sync-leaves-open-parts-to-the-run", 'parts_open "$wt/.sclaude/local/feature/state.json"; then' in fh.read(), True)
with open(os.path.join(LIB, "review", "local_review.sh")) as fh:
    lr_src = fh.read()
check("local-review-whole-from-main", 'merge-base origin/main "$head"' in lr_src, True)
check("local-review-delta-skips-merges", "--first-parent --no-merges" in lr_src, True)
check("local-review-block-first-read", 'scope="$(blocks_scope "$wt" "$head"' in lr_src, True)

for name, want, got in failures:
    print("FAIL %s: want %r, got %r" % (name, want, got))
if failures:
    print("%d failed" % len(failures))
    sys.exit(1)
print("parts: ok")
