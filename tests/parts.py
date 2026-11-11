#!/usr/bin/env python3
#
# A feature built in parts (parts.sh, plan_parts.py): one issue, one plan,
# one QA; the parts built one after another, the whole accepted, then a pull
# request for each part into the feature's common branch, reviewed in turn.
#
# Guarded here, with git real (a bare origin in a temporary directory) and gh
# faked:
#
#   * the plan's `## Parts` is read, and a criterion's `[part n]`; a plan
#     with one part, parts out of order, or a section quoted in a fence is
#     not split; each part's prompt gets its own criteria and the feature's;
#   * parts_capture puts the parts into the state, and parts_enter puts the
#     tree on the part — made off the part before it while building, the last
#     part for the whole, and for a review the part's branch with the common
#     branch merged in (pushed for the pull request's base); work done on the
#     common branch before the split becomes part 1, the common branch put
#     back where it left main; never over uncommitted work, and a merge that
#     conflicts is undone;
#   * parts_built goes on to the next part, and after the last to the whole;
#   * parts_check finds what a hand on GitHub could have done: a base edited,
#     a part merged or marked ready before its review closed, a branch
#     rewritten or moved on there;
#   * parts_advance merges the part's pull request, puts the tree on the common
#     branch with it, starts the next part's pull request and review afresh —
#     keeping the list of conversations and the whole's step 2 — and after the
#     last part goes on to the feature's pull request;
#   * `sclaude parts <name> stop` while building checks the whole on the last
#     part kept, and is refused once the whole is accepted;
#   * the local review's journal and its waiting findings are kept per pull
#     request, and its base is the common branch while a part is reviewed;
#   * the menu says which part, and the prompts say what a part is.
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
                 "tree/sync", "tree/parts", "core/cycle_steps"):
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
    out, rc = run_bash('parts_check "%s"' % wt, wt, bin_dir)
    check("nothing-to-check-while-building", (rc, out.strip()), (0, ""))

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

    # Accepted: part 1's pull request, into the common branch.
    # The product's pre-push hook refuses every push of the common branch
    # here: still where it left main, it carries nothing for the hook to
    # judge and goes up past it. The parts' branches meet the hook, all in
    # one push.
    hooks = os.path.join(tmp, "refusing-hooks")
    hook_log = os.path.join(tmp, "pre-push.log")
    os.makedirs(hooks, exist_ok=True)
    with open(os.path.join(hooks, "pre-push"), "w") as fh:
        fh.write('#!/bin/sh\nrefs="$(cat)"\necho "$refs" | awk \'{ printf "%%s ", $3 } END { print "" }\' >> "%s"\n'
                 'echo "$refs" | grep -q " refs/heads/feat/t [0-9a-f]*$" || exit 0\n'
                 'echo refused by the hook >&2\nexit 1\n' % hook_log)
    os.chmod(os.path.join(hooks, "pre-push"), 0o755)
    git("config", "core.hooksPath", hooks, cwd=wt)
    st = read_state(); st["parts"]["accepted"] = True; st["step"] = "pr"; write_state(st)
    out, rc = run_bash('parts_enter "%s"' % wt, wt, bin_dir)
    git("config", "--unset", "core.hooksPath", cwd=wt)
    check("review-starts-at-part-1", (rc, git("branch", "--show-current", cwd=wt)), (0, "feat/t-1"))
    check("umbrella-push-not-refused-by-the-hook", "refused by the hook" in out, False)
    check("the-parts-meet-the-hook-in-one-push", open(hook_log).read().split("\n")[0].split(),
          ["refs/heads/feat/t-1", "refs/heads/feat/t-2"])
    check("the-parts-on-github", [bool(git("ls-remote", "--heads", "origin", b, cwd=wt)) for b in ("feat/t-1", "feat/t-2")],
          [True, True])
    # A common branch that carries a commit main lacks still meets the hook.
    git("branch", "-q", "carrying", "feat/t-1", cwd=wt)
    out, rc = run_bash('parts_in_main "%s" refs/heads/feat/t && echo IN; parts_in_main "%s" refs/heads/carrying || echo OUT'
                       % (wt, wt), wt, bin_dir)
    git("branch", "-q", "-D", "carrying", cwd=wt)
    check("only-a-branch-all-in-main-skips-the-hook", out.split(), ["IN", "OUT"])
    check("umbrella-on-github-for-the-base",
          bool(git("ls-remote", "--heads", "origin", "feat/t", cwd=wt)), True)
    out, rc = run_bash('step_label pr "%s"; parts_base "%s"' % (wt, spath), wt, bin_dir)
    check("review-label-and-base", out.split()[-1], "feat/t")

    # The part's pull request; its review deletes the helper.
    git("rm", "-q", "helper.txt", cwd=wt)
    with open(os.path.join(wt, "a.txt"), "w") as fh:
        fh.write("part one, reviewed\n")
    git("add", "a.txt", cwd=wt)
    git("commit", "-q", "-m", "review: no helper, a.txt reworded", cwd=wt)
    git("push", "-q", "-u", "origin", "feat/t-1", cwd=wt)
    head1 = git("rev-parse", "HEAD", cwd=wt)
    prs = {"101": {"baseRefName": "feat/t", "headRefName": "feat/t-1", "state": "OPEN",
                   "isDraft": True, "headRefOid": head1}}
    with open(prs_file, "w") as fh:
        json.dump(prs, fh)
    st = read_state(); st["parts"]["1"]["pr"] = 101; st["pr"] = 101; write_state(st)
    out, rc = run_bash('parts_check "%s"' % wt, wt, bin_dir)
    check("all-holds", (rc, out.strip()), (0, ""))
    out, rc = run_bash('parts_head "%s" 101 feat/t-1; parts_head "%s" 999 feat/t-1' % (wt, wt), wt, bin_dir)
    check("the-merged-head-is-githubs-and-the-branch-without-it", out.split(), [head1, "feat/t-1"])
    st = read_state()
    check("a-merge-by-sclaude-checked-once", st["parts"]["1"].get("before"), None)

    def problems(change, moment=""):
        bad = json.loads(json.dumps(prs))
        bad["101"].update(change)
        with open(prs_file, "w") as fh:
            json.dump(bad, fh)
        got, code = run_bash('parts_check "%s" %s' % (wt, moment), wt, bin_dir)
        with open(prs_file, "w") as fh:
            json.dump(prs, fh)
        return code, got

    code, got = problems({"baseRefName": "main"})
    check("base-edited", (code, "gh pr edit 101 --base feat/t" in got), (1, True))
    code, got = problems({"state": "MERGED"})
    check("merged-early", (code, "merged by hand" in got), (1, True))
    code, got = problems({"isDraft": False})
    check("ready-early", (code, "marked ready by hand" in got), (1, True))
    code, got = problems({"isDraft": False}, "merge")
    check("ready-at-the-merge-is-fine", code, 0)
    code, got = problems({"headRefOid": base})
    check("behind-github-is-fine", code, 0)
    # A rewritten branch: GitHub's head is a commit the tree does not descend from.
    git("switch", "-q", "-c", "elsewhere", base, cwd=wt)
    git("commit", "-q", "--allow-empty", "-m", "rewritten", cwd=wt)
    other = git("rev-parse", "HEAD", cwd=wt)
    git("switch", "-q", "feat/t-1", cwd=wt)
    code, got = problems({"headRefOid": other})
    check("rewritten-on-github", (code, "rewritten there" in got), (1, True))

    # parts_advance: merged into the common branch, the next part afresh.
    st = read_state()
    st["steps"]["code"] = {"session": "cw", "done": True, "runs": [{"session": "c1"}, {"session": "cw"}]}
    st["steps"]["pr"] = {"session": "p1", "done": True, "runs": [{"session": "p1"}]}
    st["steps"]["review"] = {"session": "r1", "done": True, "rounds": 3, "enough": True,
                             "runs": [{"session": "r1"}]}
    st["step"] = "review"
    write_state(st)
    # The same refusing hook: the common branch, with main merged in by the
    # sync (an empty commit stands for it), goes up past it.
    git("config", "core.hooksPath", hooks, cwd=wt)
    out, rc = run_bash('parts_advance "%s" t' % wt, wt, bin_dir,
                       'sync_branch() { echo SYNC_BRANCH; git -C "$1" commit -q --allow-empty --no-verify -m "main in"; }\n')
    git("config", "--unset", "core.hooksPath", cwd=wt)
    check("advance-ok", rc, 0)
    check("synced-umbrella-push-not-refused-by-the-hook",
          ("refused by the hook" in out, git("rev-parse", "feat/t", cwd=wt) == git("ls-remote", "origin", "refs/heads/feat/t", cwd=wt).split()[0]),
          (False, True))
    st = read_state()
    check("part-1-merged-recorded", bool(st["parts"]["1"].get("merged")), True)
    check("on-to-part-2", st["parts"].get("current"), 2)
    check("next-part-starts-at-its-pr", (st.get("step"), "RUN_STEP pr" in out), ("pr", True))
    check("pr-cleared", st.get("pr"), None)
    check("review-afresh", st["steps"]["review"], {"runs": [{"session": "r1"}]})
    check("the-wholes-step-2-stays", st["steps"]["code"].get("session"), "cw")
    check("part-1-steps-kept", st["parts"]["1"]["steps"]["review"].get("rounds"), 3)
    check("synced-between-parts", "SYNC_BRANCH" in out, True)
    check("pr-marked-ready-before-merge", "pr ready 101" in open(os.path.join(tmp, "gh.log")).read(), True)
    check("tree-on-the-common-branch", git("branch", "--show-current", cwd=wt), "feat/t")
    check("common-branch-has-part-1", os.path.exists(os.path.join(wt, "a.txt")), True)
    # Part 1 with no pull request on record and its branch gone from GitHub:
    # origin/feat/t-1, left from the push before its review, is not taken as
    # the head its review left.
    saved = read_state()
    st = read_state(); st["parts"]["1"]["pr"] = None; write_state(st)
    gone = git("rev-parse", "origin/feat/t-1", cwd=wt)
    git("push", "-q", "--no-verify", "origin", "--delete", "feat/t-1", cwd=wt)
    git("update-ref", "refs/remotes/origin/feat/t-1", gone, cwd=wt)
    out, rc = run_bash('parts_take_common "%s" "%s" 2' % (wt, spath), wt, bin_dir)
    check("a-stale-copy-of-the-part-before-is-not-its-reviewed-head",
          (rc, "origin has no feat/t-1" in out), (1, True))
    # Origin not reached is not "origin has no branch": no push is asked for.
    url = git("remote", "get-url", "origin", cwd=wt)
    git("remote", "set-url", "origin", url + ".nowhere", cwd=wt)
    out, rc = run_bash('parts_take_common "%s" "%s" 2' % (wt, spath), wt, bin_dir)
    git("remote", "set-url", "origin", url, cwd=wt)
    check("origin-not-reached-waits-without-a-push-asked",
          (rc, "could not be fetched from origin" in out, "git push origin" in out), (1, True, False))
    git("push", "-q", "--no-verify", "origin", "%s:refs/heads/feat/t-1" % gone, cwd=wt)
    write_state(saved)
    # Run again over the same part (as run_step does after a cut-off run):
    # the merge is not recorded twice, and the part's steps stay kept.
    st = read_state(); st["parts"]["current"] = 1; st["step"] = "review"; write_state(st)
    git("switch", "-q", "feat/t", cwd=wt)
    out, rc = run_bash('parts_advance "%s" t merged' % wt, wt, bin_dir)
    st = read_state()
    with open(os.path.join(fdir, "history.jsonl")) as fh:
        merges = [l for l in fh if '"op": "merged"' in l and '"what": "parts"' in l]
    check("a-merge-recorded-once", len(merges), 1)
    check("the-hand-commit-check-passed-and-kept", read_state()["parts"]["1"].get("before"), "checked")
    check("kept-steps-not-overwritten", st["parts"]["1"]["steps"]["review"].get("rounds"), 3)
    check("on-to-part-2-again", st["parts"]["current"], 2)

    # Part 2's branch takes in part 1 as reviewed (a conflict: the sync
    # session, stubbed, keeps both) and the common branch (part 1's squash
    # recorded, no second conflict): its diff is its own.
    resolve = ('sync_with_main() { echo "SYNC $SYNC_FROM"; '
               'git -C "$1" merge -q --no-edit "$(sync_source)" >/dev/null 2>&1; '
               'printf "part one, reviewed\\npart two uses it\\n" > "$1/a.txt"; '
               'git -C "$1" add a.txt && git -C "$1" commit -q --no-edit; return 3; }\n')
    out, rc = run_bash('parts_enter "%s"' % wt, wt, bin_dir, resolve)
    check("enter-part-2-review", (rc, out if rc else ""), (0, ""))
    check("one-sync-session-for-the-part-before-none-for-its-squash",
          [l for l in out.splitlines() if l.startswith("SYNC ")], ["SYNC feat/t-1"])
    check("on-part-2-again", git("branch", "--show-current", cwd=wt), "feat/t-2")
    git("fetch", "-q", "origin", cwd=wt)
    check("part-2-has-the-common-branch",
          subprocess.run(["git", "merge-base", "--is-ancestor", "origin/feat/t", "HEAD"], cwd=wt).returncode, 0)
    check("part-2-diff-is-its-own", git("diff", "--name-only", "origin/feat/t...HEAD", cwd=wt).split(), ["a.txt", "b.txt"])
    check("part-2-diff-on-part-1s-file-is-its-line",
          [l for l in git("diff", "origin/feat/t...HEAD", "--", "a.txt", cwd=wt).splitlines()
           if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))], ["+part two uses it"])
    check("what-part-1s-review-deleted-stays-deleted", os.path.exists(os.path.join(wt, "helper.txt")), False)
    check("the-sync-session-names-the-part", read_state().get("branch"), "feat/t-2")
    git("push", "-q", "-u", "origin", "feat/t-2", cwd=wt)
    prs["102"] = {"baseRefName": "feat/t", "headRefName": "feat/t-2", "state": "OPEN",
                  "isDraft": True, "headRefOid": git("rev-parse", "HEAD", cwd=wt)}
    prs["101"]["state"] = "MERGED"
    with open(prs_file, "w") as fh:
        json.dump(prs, fh)
    st = read_state(); st["parts"]["2"]["pr"] = 102; st["pr"] = 102; st["step"] = "review"
    write_state(st)
    out, rc = run_bash('parts_base "%s"' % spath, wt, bin_dir)
    check("review-base-is-the-common-branch", out.strip(), "feat/t")
    out, rc = run_bash('parts_advance "%s" t' % wt, wt, bin_dir)
    st = read_state()
    check("last-part-closes-the-loop", st["parts"].get("done"), True)
    check("the-features-pr-next", (st.get("step"), "RUN_STEP pr" in out), ("pr", True))
    check("state-back-on-the-common-branch", st.get("branch"), "feat/t")
    check("both-parts-in", all(os.path.exists(os.path.join(wt, f)) for f in ("a.txt", "b.txt")), True)
    out, rc = run_bash('parts_base "%s"; step_label pr "%s"' % (spath, wt), wt, bin_dir)
    check("after-the-parts-main-and-a-plain-label", out.split()[0], "main")
    check("after-the-parts-no-part-in-the-label", "part" in out, False)
    out, rc = run_bash('parts_branches "%s"' % spath, wt, bin_dir)
    check("branches-for-the-clean-up", out.split(), ["feat/t-1", "feat/t-2"])
    out, rc = run_bash('parts_check "%s" final' % wt, wt, bin_dir)
    check("final-check-holds", (rc, out.strip()), (0, ""))
    prs["102"]["state"] = "OPEN"
    with open(prs_file, "w") as fh:
        json.dump(prs, fh)
    out, rc = run_bash('parts_check "%s" final' % wt, wt, bin_dir)
    check("final-check-finds-a-part-open", (rc, "still open" in out), (1, True))

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

    # The part before's reviewed head nowhere to be found: the part waits,
    # never merging the local branch in its place.
    lone = os.path.join(tmp, "lone.json")
    with open(lone, "w") as fh:
        json.dump({"feature": "t", "parts": {"total": 2, "umbrella": "zz", "current": 2}}, fh)
    git("branch", "-q", "zz-1", base, cwd=wt)
    out, rc = run_bash('parts_take_common "%s" "%s" 2' % (wt, lone), wt, bin_dir)
    check("no-reviewed-head-holds-the-part", (rc, "no pull request of part 1 is on record" in out), (1, True))
    git("branch", "-q", "-D", "zz-1", cwd=wt)

    # A part rebased onto the common branch (a rebase-only repository, or by
    # hand on GitHub), over lines that moved there meanwhile: its run of
    # commits is found by the tree it leaves and recorded — a line its review
    # removed stays removed, and nothing goes to a session.
    git("switch", "-q", "-c", "rb", base, cwd=wt)
    with open(os.path.join(wt, "r.txt"), "w") as fh:
        fh.write("a\nb\nc\nd\n")
    git("add", "r.txt", cwd=wt)
    git("commit", "-q", "-m", "r base", cwd=wt)
    git("push", "-q", "origin", "rb", cwd=wt)
    git("switch", "-q", "-c", "rb-1", cwd=wt)
    with open(os.path.join(wt, "r.txt"), "w") as fh:
        fh.write("a\nb\nX\nc\nd\n")
    git("commit", "-q", "-am", "part one adds X", cwd=wt)
    with open(os.path.join(wt, "r.txt"), "w") as fh:
        fh.write("a\nb\nX\nc\nd\ne\n")
    git("commit", "-q", "-am", "part one adds e", cwd=wt)
    git("switch", "-q", "-c", "rb-2", cwd=wt)
    with open(os.path.join(wt, "s.txt"), "w") as fh:
        fh.write("part two\n")
    git("add", "s.txt", cwd=wt)
    git("commit", "-q", "-m", "part two", cwd=wt)
    git("switch", "-q", "rb-1", cwd=wt)
    with open(os.path.join(wt, "r.txt"), "w") as fh:
        fh.write("a\nb\nc\nd\ne\n")
    git("commit", "-q", "-am", "review: no X", cwd=wt)
    git("push", "-q", "origin", "rb-1", cwd=wt)
    git("switch", "-q", "rb", cwd=wt)
    with open(os.path.join(wt, "r.txt"), "w") as fh:
        fh.write("A\nb\nc\nd\n")
    git("commit", "-q", "-am", "context moved", cwd=wt)
    git("cherry-pick", "rb-1~2", "rb-1~1", "rb-1", cwd=wt)
    git("push", "-q", "origin", "rb", cwd=wt)
    git("switch", "-q", "rb-2", cwd=wt)
    rbstate = os.path.join(tmp, "rb.json")
    with open(rbstate, "w") as fh:
        json.dump({"feature": "t", "parts": {"total": 2, "umbrella": "rb", "current": 2}}, fh)
    out, rc = run_bash('parts_take_common "%s" "%s" 2' % (wt, rbstate), wt, bin_dir,
                       'sync_with_main() { echo "SYNC $SYNC_FROM"; return 1; }\n')
    check("a-rebased-part-is-found-by-its-tree", (rc, "SYNC" in out), (0, False))
    with open(os.path.join(wt, "r.txt")) as fh:
        check("what-the-review-removed-stays-removed", fh.read(), "A\nb\nc\nd\ne\n")
    check("after-a-rebase-the-diff-is-the-part", git("diff", "--name-only", "origin/rb...HEAD", cwd=wt), "s.txt")

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
    st["parts"].update({"done": False, "current": 2, "2": {"branch": "feat/t-2", "pr": 102}})
    st["parts"].pop("dropped", None)
    write_state(st)
    run_bash('history_add "%s" qa in; session_runs "%s" steps.code open s9' % (spath, spath), wt, bin_dir)
    with open(os.path.join(fdir, "history.jsonl")) as fh:
        last = json.loads(fh.read().splitlines()[-1])
    check("history-row-names-the-part",
          (last.get("part"), last.get("part_branch"), last.get("part_pr")), ("2", "feat/t-2", "102"))
    check("a-run-names-the-part", read_state()["steps"]["code"]["runs"][-1].get("part"), "2")
    st = read_state(); st["parts"]["accepted"] = False; write_state(st)
    run_bash('history_add "%s" qa mid' % spath, wt, bin_dir)
    with open(os.path.join(fdir, "history.jsonl")) as fh:
        check("checking-the-whole-is-the-whole", json.loads(fh.read().splitlines()[-1]).get("part"), "whole")
    st = read_state(); st["parts"]["done"] = True; write_state(st)
    run_bash('history_add "%s" qa out' % spath, wt, bin_dir)
    with open(os.path.join(fdir, "history.jsonl")) as fh:
        check("after-the-parts-the-whole", json.loads(fh.read().splitlines()[-1]).get("part"), "whole")

    # What the common branch took past a part: neither its squash nor its
    # own commits (a rebase merge), only what was put there by hand.
    git("switch", "-q", "-c", "x-common", "feat/t", cwd=wt)
    before = git("rev-parse", "HEAD", cwd=wt)
    git("switch", "-q", "-c", "x-part", cwd=wt)
    for name in ("p1", "p2"):
        with open(os.path.join(wt, name), "w") as fh:
            fh.write(name + "\n")
        git("add", name, cwd=wt)
        git("commit", "-q", "-m", name, cwd=wt)
    git("switch", "-q", "x-common", cwd=wt)
    git("merge", "-q", "--squash", "x-part", cwd=wt)
    git("commit", "-q", "-m", "squashed part", cwd=wt)
    with open(os.path.join(wt, "hand"), "w") as fh:
        fh.write("hand\n")
    git("add", "hand", cwd=wt)
    git("commit", "-q", "-m", "by hand", cwd=wt)
    out, rc = run_bash('parts_extra "%s" %s HEAD x-part' % (wt, before), wt, bin_dir)
    check("extra-after-a-squash", [l.split(" ", 1)[1] for l in out.splitlines()], ["by hand"])
    # Merged from GitHub's head, which took a suggestion the tree never had:
    # read by that head, the squash is the part's.
    git("reset", "-q", "--hard", before, cwd=wt)
    git("switch", "-q", "-c", "x-github", "x-part", cwd=wt)
    with open(os.path.join(wt, "p1"), "a") as fh:
        fh.write("suggested\n")
    git("commit", "-q", "-am", "suggestion", cwd=wt)
    gh_head = git("rev-parse", "HEAD", cwd=wt)
    git("switch", "-q", "x-common", cwd=wt)
    git("merge", "-q", "--squash", "x-github", cwd=wt)
    git("commit", "-q", "-m", "squashed from github", cwd=wt)
    out, rc = run_bash('parts_extra "%s" %s HEAD %s' % (wt, before, gh_head), wt, bin_dir)
    check("extra-read-by-the-merged-head", out.strip(), "")
    git("reset", "-q", "--hard", before, cwd=wt)
    git("cherry-pick", "x-part~1", "x-part", cwd=wt)
    with open(os.path.join(wt, "hand2"), "w") as fh:
        fh.write("hand\n")
    git("add", "hand2", cwd=wt)
    git("commit", "-q", "-m", "by hand after", cwd=wt)
    out, rc = run_bash('parts_extra "%s" %s HEAD x-part' % (wt, before), wt, bin_dir)
    check("extra-after-a-rebase", [l.split(" ", 1)[1] for l in out.splitlines()], ["by hand after"])
    # A hand commit beside the part's lines, then the part squashed over it:
    # the squash's context differs, and it is still the part's.
    git("reset", "-q", "--hard", before, cwd=wt)
    with open(os.path.join(wt, "lines"), "w") as fh:
        fh.write("a\nb\nc\nd\n")
    git("add", "lines", cwd=wt)
    git("commit", "-q", "-m", "lines", cwd=wt)
    base2 = git("rev-parse", "HEAD", cwd=wt)
    git("switch", "-q", "-c", "x-part2", cwd=wt)
    with open(os.path.join(wt, "lines"), "w") as fh:
        fh.write("a\nb\nC\nd\n")
    git("commit", "-q", "-am", "part edits c", cwd=wt)
    git("switch", "-q", "x-common", cwd=wt)
    with open(os.path.join(wt, "lines"), "w") as fh:
        fh.write("A\nb\nc\nd\n")
    git("commit", "-q", "-am", "hand edits a", cwd=wt)
    git("merge", "-q", "--squash", "x-part2", cwd=wt)
    git("commit", "-q", "-m", "squashed part 2", cwd=wt)
    out, rc = run_bash('parts_extra "%s" %s HEAD x-part2' % (wt, base2), wt, bin_dir)
    check("extra-by-tree-when-the-context-moved", [l.split(" ", 1)[1] for l in out.splitlines()], ["hand edits a"])
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
code = render("code", dict(IN_PART, SCLAUDE_V_IN_PARTS="", SCLAUDE_V_PART_ALONE="", SCLAUDE_V_ASKS_ACCEPT="1",
                           SCLAUDE_V_PART_AGAIN="1"))
check("step-2-during-a-parts-review-is-that-part", ("part 2 of 3 — Tickets" in code, "No part has a pull request" in code),
      (True, False))
code = render("code", WHOLE)
check("whole-feature-session-is-accepted", "Accept work" in code, True)
check("whole-feature-session-on-the-last-part", "the tree is on the last part's branch" in code, True)
check("nothing-dropped-nothing-said", "ended the parts early" in code, False)
dropped = render("code", dict(WHOLE, SCLAUDE_V_PARTS_DROPPED="2-3", SCLAUDE_V_ISSUE="41"))
check("dropped-parts-are-struck-and-filed",
      "parts 2-3" in dropped and "~~AC7. …~~" in dropped and "issues/41/sub_issues" in dropped, True)
code = render("code", DONE)
check("after-the-parts-a-plain-step-2", ("Accept work" in code, "built in parts" in code), (True, False))
pr = render("pr", IN_PART)
check("part-pr-into-the-common-branch", "gh pr create --base feat/t" in pr, True)
check("part-pr-refs-the-issue", "`Refs #41`" in pr and "`Closes #41`" not in pr, True)
check("part-pr-reads-its-base", "origin/feat/t..HEAD" in pr, True)
pr = render("pr", DONE)
check("feature-pr-closes-the-issue", "`Closes #41`" in pr, True)
check("feature-pr-lists-the-parts", "Built in parts" in pr, True)
review = render("review", IN_PART)
check("part-review-diffs-its-base", "git diff origin/feat/t...HEAD" in review, True)
check("part-review-knows-its-part", "part 2 of 3" in review, True)
review = render("review", DONE)
check("feature-review-reads-the-seams", "the seams between the parts" in review, True)
plan = render("plan", dict(DONE, SCLAUDE_V_IN_PARTS=""))
check("plan-asks-for-the-parts-section", "`### Part <n> — <title>`" in plan, True)
check("plan-files-no-issue-for-a-part", "gh issue create" in plan, False)

# --- the cycle's code carries the hooks ---------------------------------------------------
with open(os.path.join(LIB, "cycle", "run.sh")) as fh:
    run_src = fh.read()
check("a-parts-review-advances", 'parts_reviewing "$state"; then\n    parts_advance' in run_src, True)
check("a-part-built-goes-on", 'parts_building "$state"; then\n    parts_built' in run_src, True)
check("no-main-into-a-part", "parts_check_say \"$wt\" || {" in run_src, True)
with open(os.path.join(LIB, "commands", "feature_commands.sh")) as fh:
    check("sclaude-sync-leaves-open-parts-to-the-run", 'parts_open "$wt/.sclaude/local/feature/state.json"; then' in fh.read(), True)
with open(os.path.join(LIB, "review", "local_review.sh")) as fh:
    lr_src = fh.read()
check("local-review-base-is-the-prs", 'merge-base "origin/$into"' in lr_src, True)
check("local-review-delta-skips-merges", "--first-parent --no-merges" in lr_src, True)

for name, want, got in failures:
    print("FAIL %s: want %r, got %r" % (name, want, got))
if failures:
    print("%d failed" % len(failures))
    sys.exit(1)
print("parts: ok")
