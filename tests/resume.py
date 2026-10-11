#!/usr/bin/env python3
#
# An integration bench: `sclaude <feature>` from the outside, end to end.
#
# Every other bench in this directory calls one function and checks what it did.
# That is the right shape for a function whose failure is silent, and it is blind
# to the failure this file exists for: **each link correct, the chain wrong**.
#
# It has already happened twice, and both were found by a reviewer rather than by
# these tests:
#
#   * `watch_rewind` put the cycle back on `review`, and `run_step` — two lines
#     later — saw the merged pull request, concluded there was nothing to do and
#     set the step back to `done`. The rewind was undone in the same breath it
#     was made, and the preview verdict destroyed on the way. tests/qa-return.py
#     called `watch_rewind` directly and passed.
#
#   * the `done` verdict was never acknowledged, because `watch_seen` is called
#     from inside `run_step` and a passed feature goes to `remind_prod` instead.
#     The banner would have printed on every run until the clean-up.
#
# So this one enters where a person does — `cmd_resume` — and asserts on the
# state after the whole chain has run. `claude` is replaced by a stub that writes
# the transcript line `session_started` looks for and records the prompt it was
# given; everything else is the real orchestrator against a real git repository.
#
# What it cannot do is launch a model, so a step here always "runs" instantly.
# That is enough: the failures this guards against are transitions, and every one
# of them happens before or after the session rather than inside it.
#
# Run it with: python3 tests/resume.py
import json
import os
import pty
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCLAUDE = os.path.join(ROOT, "bin", "sclaude")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


def git(*args, cwd):
    return subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True,
                          text=True, check=False)


def encoded(path):
    """The transcript directory's name — transcript_dir's rule, in python."""
    return "".join(c if c.isalnum() else "-" for c in path)


class World:
    """A repository, a worktree, a fake HOME and a fake PATH.

    The stubs go in a directory ahead of everything on PATH: `claude` writes a
    transcript and records its prompt, `gh` and `vercel` answer nothing. Nothing
    here reaches the network, and nothing costs a token.
    """

    def __init__(self, root, merged=True):
        self.root = root
        self.home = os.path.join(root, "home")
        self.bin = os.path.join(root, "bin")
        self.repo = os.path.join(root, "repo")
        self.wt = os.path.join(root, "repo-demo")
        os.makedirs(self.bin)
        os.makedirs(os.path.join(self.home, ".claude"))

        # --- the repository and a feature's worktree -------------------------
        os.makedirs(self.repo)
        git("init", "-q", "-b", "main", cwd=self.repo)
        git("config", "user.email", "t@t", cwd=self.repo)
        git("config", "user.name", "T", cwd=self.repo)
        with open(os.path.join(self.repo, "README.md"), "w") as fh:
            fh.write("x\n")
        # A config, so the regression has something to say about this project —
        # without one the gate reports "no regression declared" and the step
        # would close for a reason this bench is not about.
        with open(os.path.join(self.repo, ".sclaude.json"), "w") as fh:
            json.dump({"commands": {"noop": "true"},
                       "regression": {"local": ["noop"]}}, fh)
        git("add", "-A", cwd=self.repo)
        git("commit", "-qm", "first", cwd=self.repo)

        origin = os.path.join(root, "origin.git")
        subprocess.run(["git", "clone", "-q", "--bare", self.repo, origin],
                       capture_output=True, check=False)
        git("remote", "add", "origin", origin, cwd=self.repo)
        git("fetch", "-q", "origin", cwd=self.repo)
        git("branch", "-q", "feat/demo", cwd=self.repo)
        subprocess.run(["git", "worktree", "add", "-q", self.wt, "feat/demo"],
                       cwd=self.repo, capture_output=True, check=False)

        self.merged = merged
        self.stub_claude()
        self.stub_gh()
        self.stub_misc()

    # --- the stubs -----------------------------------------------------------

    def write(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w") as fh:
            fh.write("#!/usr/bin/env bash\n" + body)
        os.chmod(path, 0o755)

    def stub_claude(self):
        """Records the prompt, then writes the transcript session_started wants.

        Without that line the orchestrator decides the session never started and
        returns early — which is a real path, but not the one under test.
        """
        self.write("claude", r'''
prompts="$SCLAUDE_TEST_PROMPTS"
session=""
prompt=""
prev=""
for arg in "$@"; do
  case "$prev" in
    --resume|--session-id) session="$arg" ;;
  esac
  [[ "$arg" == -* || "$prev" == -n ]] || prompt="$arg"
  prev="$arg"
done
printf '%s\n' "$prompt" >> "$prompts"
# The transcript session_started looks for, unless the test asked for a session
# that never got going. Writing it makes the orchestrator carry on into
# after_step, which closes the step and runs the whole epilogue — useful for
# some cases and wrong for the ones that are about the transition itself.
if [[ "${SCLAUDE_TEST_STILLBORN:-0}" != "1" ]]; then
  dir="$HOME/.claude/projects/$(printf '%s' "$PWD" | sed 's/[^a-zA-Z0-9]/-/g')"
  mkdir -p "$dir"
  printf '{"type":"assistant","message":{"content":[]}}\n' > "$dir/$session.jsonl"
fi
exit 0
''')

    def stub_gh(self):
        """`gh pr view --json state` answers whatever the merge file says.

        Read from a file rather than baked in, because step 4 waits for the
        merge in a loop that ends only when one is reported. A stub that could
        never say MERGED would hang the bench there; this way the test can let
        the wait run and then answer it.
        """
        self.merge_file = os.path.join(self.root, "merge-state")
        with open(self.merge_file, "w") as fh:
            fh.write("MERGED" if self.merged else "OPEN")
        self.write("gh", '''
for arg in "$@"; do
  if [[ "$arg" == *state* ]]; then cat "%s"; exit 0; fi
done
exit 1
''' % self.merge_file)

    def stub_misc(self):
        for name in ("vercel", "npm", "npx", "node", "chrome-debug"):
            self.write(name, "exit 0\n")

        # `git`, with exactly one subcommand taken away.
        #
        # This is not caution. `cmd_resume` calls `push_instruments`
        # unconditionally, and that pushes `$INSTRUMENTS` — which
        # `readlink -f "$0"` resolves to the *real* repository this bench lives
        # in, whatever HOME says. Left alone, running the test suite pushes the
        # developer's unpushed commits to GitHub: verified in the act, with
        # `git -C ~/instruments push origin main` visible in `ps` while
        # the bench ran.
        #
        # It also made the bench's verdict a function of network latency. The
        # push hung on a credential prompt, the run was killed at its timeout
        # before reaching `watch_seen`, and two assertions failed with nothing to
        # suggest why.
        #
        # A refusal rather than a silent success: `push_instruments` reports a
        # failed push in words and carries on, which is the path this bench
        # should exercise anyway. Everything else is the real git — the fixture
        # is a real repository and the orchestrator reads it constantly.
        self.write("git", '''
# The subcommand is the first word that is neither a flag nor a flag's value.
# `git -C <dir> push ...` is the shape that matters here, so the `-C` path must
# be stepped over rather than mistaken for it.
skip=0
sub=""
for arg in "$@"; do
  if [[ "$skip" -eq 1 ]]; then skip=0; continue; fi
  case "$arg" in
    -C|-c|--git-dir|--work-tree|--namespace) skip=1 ;;
    -*) ;;
    *) sub="$arg"; break ;;
  esac
done
if [[ "$sub" == "push" ]]; then
  echo "push refused: the bench does not touch a remote" >&2
  exit 1
fi
exec %s "$@"
''' % shutil.which("git"))

    # --- running it ----------------------------------------------------------

    def state(self, path):
        out = subprocess.run(
            ["python3", "-c",
             "import json,sys\n"
             "d=json.load(open(sys.argv[1]))\n"
             "for k in sys.argv[2].split('.'):\n"
             "    d = d.get(k) if isinstance(d, dict) else None\n"
             "    if d is None: print(''); raise SystemExit\n"
             "print(d if not isinstance(d, bool) else str(d).lower())",
             os.path.join(self.wt, ".feature", "state.json"), path],
            capture_output=True, text=True)
        return out.stdout.strip()

    def set_state(self, blob):
        os.makedirs(os.path.join(self.wt, ".feature"), exist_ok=True)
        with open(os.path.join(self.wt, ".feature", "state.json"), "w") as fh:
            json.dump(blob, fh)

    def watch(self, blob, notes=None):
        d = os.path.join(self.home, ".claude", "sclaude", "watch")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "demo.json"), "w") as fh:
            json.dump(blob, fh)
        if notes is not None:
            with open(os.path.join(d, "demo.qa.md"), "w") as fh:
                fh.write(notes)

    def watch_field(self, key):
        path = os.path.join(self.home, ".claude", "sclaude", "watch", "demo.json")
        try:
            with open(path) as fh:
                value = json.load(fh).get(key)
        except (OSError, ValueError):
            return ""
        return "" if value is None else str(value)

    def resume(self, answers="n\n" * 20, timeout=120, stillborn=False):
        """`sclaude demo` on a real pseudo-terminal, questions answered `n`.

        A pty rather than a pipe, and not for cosmetics: a step refuses to start
        without one — `( exec < /dev/tty )` in run_step — because a session that
        goes somewhere nobody is watching never reaches after_step, and the next
        step and the friction review go with it. Under a pipe this bench would
        only ever exercise that refusal, which is not what it is for.
        """
        prompts = os.path.join(self.root, "prompts.txt")
        open(prompts, "w").close()
        env = dict(
            os.environ,
            HOME=self.home,
            PATH=self.bin + os.pathsep + os.environ["PATH"],
            SCLAUDE_TEST_PROMPTS=prompts,
            # This bench runs on a real pseudo-terminal, and run from Windows
            # Terminal it inherits $WT_SESSION: every step would open a real
            # pane on the desktop. tests/pane.py covers the pane.
            SCLAUDE_PANE="off",
            # The retrospective before the clean-up is one more claude session,
            # and the stub answers every session with the same prompt log.
            # It is not what these cases assert on; tests/terminal.py covers
            # what it reads.
            SCLAUDE_RETRO="off",
            # A session that writes no transcript. The orchestrator then reports
            # "claude exited immediately — the step never started" and leaves
            # the step where it was, which is what the transition cases want:
            # letting the stub "succeed" would close the step and run the whole
            # epilogue, and the assertion would be about the end of the cycle
            # rather than about the move that was just made.
            SCLAUDE_TEST_STILLBORN="1" if stillborn else "0",
            # The merge wait polls gh every MERGE_POLL seconds. The stub never
            # reports a merge on the unmerged path, so at its service value this
            # bench would spend half a minute per poll waiting for something
            # that cannot happen.
            MERGE_POLL="1",
            # A port nothing is on, so `dev_pid` cannot find the developer's own
            # dev server. Left at 3000 the bench reads the real machine: a
            # listener from another directory puts "restart it?" in front of a
            # fixture that answers blind, and the `n` meant for the next
            # question is spent on it.
            DEV_PORT="39517",
            # The channel ask() reads alongside the terminal. Left pointing at a
            # real one, a question here would wait on the phone.
            ASK_DIR=os.path.join(self.root, "ask"),
            # instruments_sync fetches and merges the real repository this bench
            # lives in — the same trap as the push described in stub_misc.
            SCLAUDE_NO_SYNC="1",
        )

        primary, secondary = pty.openpty()
        proc = subprocess.Popen(
            [SCLAUDE, "demo"], cwd=self.repo, env=env,
            stdin=secondary, stdout=secondary, stderr=secondary,
            close_fds=True, start_new_session=True)
        os.close(secondary)

        # Answers go in as the questions arrive; the reader drains in parallel so
        # a full pipe buffer cannot deadlock the child.
        chunks = []

        def drain():
            while True:
                try:
                    data = os.read(primary, 4096)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        try:
            try:
                os.write(primary, answers.encode())
            except OSError:
                pass
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                # A second timeout here would escape and leave `primary` open —
                # the bench runs several worlds, and a descriptor per run is a
                # leak that ends in EMFILE rather than in a failed assertion.
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            os.close(primary)
        reader.join(timeout=5)

        with open(prompts) as fh:
            self.prompts = fh.read()
        return b"".join(chunks).decode(errors="replace")


DONE_STATE = {
    "feature": "demo", "branch": "feat/demo", "worktree": None,
    "issue": None, "pr": 208, "step": "done",
    "steps": {
        "plan": {"done": True, "finished": "2026-09-10T09:00:00+03:00"},
        "code": {"done": True, "finished": "2026-09-10T14:00:00+03:00"},
        "pr": {"done": True, "finished": "2026-09-10T15:00:00+03:00"},
        "review": {"done": True, "finished": "2026-09-11T11:00:00+03:00",
                   "session": "old-session"},
    },
    "regression": {"preview": {"status": "passed", "attempts": 0},
                   "local": {"status": "passed"}},
    "deploy": {"prod": {"sha": "abc"}},
}


tmp = tempfile.mkdtemp()
try:
    # --- QA hands back a merged feature --------------------------------------
    #
    # The case the whole thing failed on. The watch is armed in remind_prod and
    # the merge is offered later in that same pass, so a feature waiting on QA
    # is merged already — and run_step's "a merged PR closes everything" branch
    # reverted the rewind two lines after it was made.

    w = World(os.path.join(tmp, "a"), merged=True)
    w.set_state(dict(DONE_STATE, worktree=w.wt))
    w.watch({"feature": "demo", "verdict": "returned", "status": "In progress"},
            notes="the avatar does not load on iOS\n")
    # stillborn: the step is launched and the session does not get going, so the
    # orchestrator leaves the step where the rewind put it. Letting the stub
    # "succeed" would close step 4 and run the epilogue, and every assertion
    # below would then be about the end of the cycle rather than about the move.
    out = w.resume(stillborn=True)

    check_true("returned-banner-shown", "was returned to development" in out)
    # The state after the whole chain, which is the assertion that was missing.
    check("returned-step-stays-review", w.state("step"), "review")
    check("returned-review-reopened", w.state("steps.review.done"), "false")
    check("returned-preview-cleared", w.state("regression.preview.status"), "")
    # And the production reminder must NOT be what the human ends up looking at.
    check("returned-no-production-reminder",
          "has been through every step" in out, False)

    # The comments reached the session rather than being filed away unread.
    check_true("returned-notes-reach-the-session",
               "avatar does not load" in w.prompts)
    # And are NOT acknowledged when the session never got going: the verdict
    # means "something changed since you last looked", and a session that did
    # not start has not looked. Acknowledging here would file the comments away
    # unread, which is the failure watch_seen's placement guards against.
    check("returned-verdict-kept-when-stillborn", w.watch_field("verdict"),
          "returned")

    # A session that does get going consumes it. Same world, run again — this
    # time the stub writes its transcript, so run_step reaches watch_seen.
    w.resume()
    check("returned-verdict-cleared-once-delivered", w.watch_field("verdict"), "")

    # --- the rewind must also survive after_step -----------------------------
    #
    # A second review found the first fix bought exactly one session: run_step
    # was guarded, after_step was not. Its review branch closes the step on "the
    # branch's pull request is merged", and after a hand-back that is still the
    # old merged one — so the step closed itself the moment the session exited,
    # with no fix pushed and no new pull request anywhere.
    #
    # Not stillborn: the session has to run and exit for after_step to be
    # reached at all. What must hold afterwards is that the step is still open.
    w = World(os.path.join(tmp, "a2"), merged=True)
    w.set_state(dict(DONE_STATE, worktree=w.wt))
    w.watch({"feature": "demo", "verdict": "returned", "status": "In progress"},
            notes="the avatar does not load on iOS\n")
    out = w.resume()
    check("after-step-does-not-close-the-reopened-review",
          w.state("step"), "review")
    check("after-step-leaves-the-review-open",
          w.state("steps.review.done"), "false")
    check_true("after-step-says-why",
               "still the pull request the feature was returned on" in out)
    # The mark names the pull request QA saw, so a genuinely new one closes the
    # step as it should.
    check("reopened-pr-recorded", w.state("reopened_pr"), "208")

    # --- the same, unmerged --------------------------------------------------
    #
    # The path that always worked. It must keep working: the guard is about a
    # step that was reopened, not about merges in general.

    # The rewind on a branch whose pull request is still open.
    #
    # This one cannot tell the `reopened` guard from its absence — with nothing
    # merged the shortcut never fires either way — and it is kept for what it
    # does cover: that the rewind happens at all on the path where the merge is
    # not in the picture, and that nothing about the guard broke it. The case
    # that exercises the guard is the merged one above.
    #
    # stillborn, because with the pull request unmerged step 4 closes by waiting
    # for the merge in a loop, and a bench that let the session start would sit
    # in it.
    w = World(os.path.join(tmp, "b"), merged=False)
    w.set_state(dict(DONE_STATE, worktree=w.wt))
    w.watch({"feature": "demo", "verdict": "returned", "status": "In progress"},
            notes="the avatar does not load on iOS\n")
    w.resume(timeout=45, stillborn=True)
    check("unmerged-step-stays-review", w.state("step"), "review")
    check("unmerged-review-reopened", w.state("steps.review.done"), "false")

    # --- QA passes it --------------------------------------------------------
    #
    # Nothing is rewound, and the banner is acknowledged where it is shown:
    # watch_seen lives inside run_step, which a passed feature never reaches, so
    # the verdict would otherwise print on every run until the clean-up.

    w = World(os.path.join(tmp, "c"), merged=True)
    w.set_state(dict(DONE_STATE, worktree=w.wt))
    w.watch({"feature": "demo", "verdict": "done", "status": "Done"})
    out = w.resume()

    check_true("done-banner-shown", "QA passed this one" in out)
    check("done-step-unchanged", w.state("step"), "done")
    check("done-review-still-closed", w.state("steps.review.done"), "true")
    check("done-verdict-cleared", w.watch_field("verdict"), "")
    # A second run says nothing: the verdict was acknowledged.
    out2 = w.resume()
    check("done-banner-not-repeated", "QA passed this one" in out2, False)

    # --- a merged feature with no verdict ------------------------------------
    #
    # The shortcut itself, which must still work. A step nobody reopened closes
    # on a merge — that is what it is for, and the `reopened` guard must not
    # have taken it away.

    w = World(os.path.join(tmp, "d"), merged=True)
    w.set_state(dict(DONE_STATE, worktree=w.wt, step="review",
                     steps=dict(DONE_STATE["steps"],
                                review={"done": False, "finished": None})))
    out = w.resume()
    check("merged-shortcut-still-closes", w.state("step"), "done")
    check("merged-shortcut-marks-review", w.state("steps.review.done"), "true")

    # --- a second resume after a hand-back -----------------------------------
    #
    # The rewind must not repeat. The verdict was cleared when the comments were
    # delivered, so the second run is an ordinary resume of the review step —
    # and, crucially, the merge must not close it behind our back either.

    w = World(os.path.join(tmp, "e"), merged=True)
    w.set_state(dict(DONE_STATE, worktree=w.wt))
    w.watch({"feature": "demo", "verdict": "returned", "status": "In progress"},
            notes="still broken\n")
    # The first pass delivers the comments and acknowledges them. The second is
    # then an ordinary resume of a step that is open: no banner, and no second
    # rewind clearing the preview verdict all over again.
    #
    # Both passes are stillborn on purpose. Letting the session succeed would
    # close step 4 — correctly, the pull request is merged — and the second run
    # would be about a finished cycle rather than about the verdict not
    # repeating, which is what this case is for.
    w.resume(stillborn=True)
    check("second-first-pass", w.state("step"), "review")
    # Not yet consumed: the session never got going, so nothing was delivered.
    check("second-verdict-held", w.watch_field("verdict"), "returned")

    # Now one that does get going, and the verdict goes with it.
    w.resume()
    check("second-verdict-consumed", w.watch_field("verdict"), "")

    # And from here the banner is gone for good.
    out = w.resume(stillborn=True)
    check("second-no-banner", "was returned to development" in out, False)

    # --- a review reopened by a preview fix, then merged ----------------------
    #
    # A red preview, a fixing session, a green rerun: regression_rewind puts the
    # cycle back on the review — and remind_prod carries on to QA, the merge and
    # production in the same run without coming back. The mark used to stay, so
    # the next run opened a review of the merged pull request that after_step
    # refused to close, waiting for a second pull request nobody needed. Feature
    # 138 was left exactly there.
    reopened_review = dict(DONE_STATE["steps"], review={"done": False, "finished": None})
    w = World(os.path.join(tmp, "f"), merged=True)
    w.set_state(dict(DONE_STATE, step="review", steps=reopened_review, worktree=w.wt,
                     reopened="review", reopened_pr=208, reopened_by="preview"))
    out = w.resume()
    check("preview-reopen-closes-on-merge", w.state("step"), "done")
    check("preview-reopen-no-review-session", w.prompts.strip(), "")
    check("preview-reopen-mark-cleared", w.state("reopened_by"), "")

    # --- a review reopened by a production rollback --------------------------
    #
    # This one must hold until a new pull request arrives — and the session must
    # be told why it is there. It used to get the ordinary review prompt, with
    # no word of the failure, the rollback or the new pull request.
    w = World(os.path.join(tmp, "g"), merged=True)
    os.makedirs(os.path.join(w.wt, ".feature"), exist_ok=True)
    kept = os.path.join(w.wt, ".feature", "regression.prod.failed.log")
    with open(kept, "w") as fh:
        fh.write("the landing page returned 500\n")
    w.set_state(dict(DONE_STATE, step="review", steps=reopened_review, worktree=w.wt,
                     reopened="review", reopened_pr=208, reopened_by="prod",
                     rollback={"prod": {"code": "done", "log": kept}},
                     regression=dict(DONE_STATE["regression"],
                                     prod={"status": "failed", "failed_at": "e2e"})))
    out = w.resume()
    check("prod-reopen-holds", w.state("step"), "review")
    check_true("prod-reopen-says-why",
               "production was rolled back from (#208)" in out)
    check_true("prod-review-told-the-failure", "prod regression failed on `e2e`" in w.prompts)
    check_true("prod-review-given-the-kept-log", "returned 500" in w.prompts)
    check_true("prod-review-told-the-rollback", "rolled back before this session" in w.prompts)
    check_true("prod-review-stays-on-the-branch", "stay on this branch" in w.prompts)
    # The gate's own instructions are not: no gate reads a note this one writes.
    check("prod-review-no-gate-note", "regression.blocked" in w.prompts, False)

    # --- a fix that left the branch ------------------------------------------
    #
    # sclaude follows the feature by the branch in its state. A fix on another
    # branch leaves that one answering MERGED, and the cycle would walk the fix
    # past the preview and QA and ship main without it. So the review does not
    # close on another branch.
    w = World(os.path.join(tmp, "h"), merged=False)
    w.set_state(dict(DONE_STATE, step="review", steps=reopened_review, worktree=w.wt))
    git("checkout", "-q", "-b", "fix/elsewhere", cwd=w.wt)
    out = w.resume(timeout=45)
    check("other-branch-review-stays-open", w.state("steps.review.done"), "false")
    check_true("other-branch-is-named", "The worktree is on fix/elsewhere" in out)

finally:
    for sub in ("a", "b", "c", "d", "e", "f", "g", "h"):
        repo = os.path.join(tmp, sub, "repo")
        wt = os.path.join(tmp, sub, "repo-demo")
        if os.path.isdir(repo):
            subprocess.run(["git", "worktree", "remove", "--force", wt],
                           cwd=repo, capture_output=True, check=False)
    shutil.rmtree(tmp, ignore_errors=True)


if failures:
    for name, want, got in failures:
        sys.stderr.write("FAIL %s\n  want: %r\n  got:  %r\n" % (name, want, got))
    sys.stderr.write("\n%d failure(s)\n" % len(failures))
    sys.exit(1)

print("ok")
