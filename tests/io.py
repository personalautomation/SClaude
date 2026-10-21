#!/usr/bin/env python3
#
# A test bench for the question-answer channel: sclaude/lib/io.sh and the
# rewritten ask from ui.sh.
#
# The main thing here is the race between two sources. A question now has two
# inputs, the terminal and the channel, and a mistake here is not "inconvenient"
# but "the step answered something other than what the human pressed": both
# inputs lead to the same is_yes, and a spurious "yes" on the prod question costs
# more than anything else in this repository.
#
# We check through a real bash rather than through logic rewritten in python: the
# point of the bench is that the very code that will go into service is what
# runs.
#
# Run it with: python3 tests/io.py
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def run_bash(script, cwd, stdin="", timeout=20):
    # We leave ASK_POLL as it is in service: a second is small enough that the
    # bench does not drag and large enough to exercise the real waiting loop.
    body = 'set -uo pipefail\nsource "%s/io.sh"\nsource "%s/ui.sh"\n%s' % (LIB, LIB, script)
    out = subprocess.run(["bash", "-c", body], cwd=cwd, input=stdin,
                         capture_output=True, text=True, timeout=timeout)
    return out.stdout, out.stderr, out.returncode


def unsweep(d):
    # ask_closed sweeps week-old records once a day, by this stamp.
    try:
        os.unlink(os.path.join(d, ".swept"))
    except OSError:
        pass


def answer_after(path, reply, delay, ask_id=None):
    # Writes an answer into the channel after delay seconds — the same thing the
    # bot will do when the human presses a button.
    #
    # ask_id is the stamp of the question being answered. None means an answer
    # from a version that did not stamp one, and that is the case to keep
    # working: the daemon and the orchestrator are updated separately.
    def worker():
        time.sleep(delay)
        tmp = path + ".tmp"
        payload = {"reply": reply}
        if ask_id is not None:
            payload["id"] = ask_id
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, path)
    thread = threading.Thread(target=worker)
    thread.daemon = True
    thread.start()
    return thread


def main():
    tmp = tempfile.mkdtemp()
    try:
        # --- laying out a question ----------------------------------------
        #
        # The caller declares the answer's form, and it must reach the channel
        # exactly as it was passed: the bot decides by it whether to draw buttons
        # or to ask for text.
        for form, want in (("yn", "yn"), ("yn:yes", "yn:yes"),
                           ("pick:7", "pick:7"), ("", "")):
            d = os.path.join(tmp, "form-" + (form or "none").replace(":", "-"))
            os.makedirs(d)
            run_bash('ASK_DIR=%s ask_publish "A question? " "%s" > /dev/null' % (d, form), tmp)
            with open(os.path.join(d, "ask.json"), encoding="utf-8") as fh:
                got = json.load(fh)
            check("form-%s" % (form or "none"), got["form"], want)
            check("prompt-%s" % (form or "none"), got["prompt"], "A question? ")

        # The context accumulated by info/warn travels with the question:
        # without it a "Publish?" in a messenger is agreement to who knows
        # what.
        d = os.path.join(tmp, "ctx")
        os.makedirs(d)
        run_bash('ASK_DIR=%s; ask_note "vercel deploy"; ask_note "  and more"; '
                 'ask_publish "Publish? " yn > /dev/null' % d, tmp)
        with open(os.path.join(d, "ask.json"), encoding="utf-8") as fh:
            got = json.load(fh)
        check("context-collected", got["context"], "vercel deploy\n  and more\n")

        # A question without a channel is not an error but an ordinary terminal
        # question: sclaude is also launched outside a repository.
        _, _, rc = run_bash('unset ASK_DIR REPO; ask_publish "A question? " yn', tmp)
        check("no-channel-rc", rc, 1)

        # --- the channel is busy with another orchestrator -----------------
        #
        # There is one channel per repository, and there may turn out to be two
        # orchestrators: one started at the laptop, the other by a button in the
        # bot. The later arrival must give way — otherwise it overwrites the
        # first's question, and that one hangs for ever, waiting for an answer
        # that will no longer go to it.
        d = os.path.join(tmp, "busy")
        os.makedirs(d)
        # A live foreign owner: we take the pid of a process that certainly
        # exists — our own. It is not equal to the pid of the shell that will
        # publish.
        with open(os.path.join(d, "ask.json"), "w", encoding="utf-8") as fh:
            json.dump({"prompt": "somebody else's question", "form": "yn", "context": "",
                       "asked": 1, "pid": os.getpid()}, fh, ensure_ascii=False)
        _, _, rc = run_bash('ASK_DIR=%s; ask_publish "my question" yn' % d, tmp)
        check("busy-refused", rc, 1)
        with open(os.path.join(d, "ask.json"), encoding="utf-8") as fh:
            check("busy-kept-original", json.load(fh)["prompt"], "somebody else's question")

        # A dead owner does not hold the channel: the orchestrator may have been
        # killed with Ctrl-C or cut off along with ssh, and a channel busy for
        # ever would mean this repository could never be reached from a phone
        # again.
        d = os.path.join(tmp, "dead")
        os.makedirs(d)
        with open(os.path.join(d, "ask.json"), "w", encoding="utf-8") as fh:
            json.dump({"prompt": "a dead process's question", "form": "yn", "context": "",
                       "asked": 1, "pid": 999999}, fh, ensure_ascii=False)
        _, _, rc = run_bash('ASK_DIR=%s; ask_publish "my question" yn > /dev/null' % d, tmp)
        check("dead-owner-rc", rc, 0)
        with open(os.path.join(d, "ask.json"), encoding="utf-8") as fh:
            check("dead-owner-taken", json.load(fh)["prompt"], "my question")

        # Our own question is overwritten freely: it is the next question of the
        # same conversation, and one step has several in a row.
        d = os.path.join(tmp, "mine")
        os.makedirs(d)
        out, _, _ = run_bash(
            'ASK_DIR=%s; ask_publish "the first" yn > /dev/null; '
            'ask_publish "the second" yn > /dev/null; '
            'python3 -c "import json;print(json.load(open(\'%s/ask.json\'))[\'prompt\'])"'
            % (d, d), tmp)
        check("own-question-replaced", out.strip(), "the second")

        # Every question has its own stamp. They cannot be told apart by time:
        # two questions in a row ("Delete them?" and immediately "Force-delete
        # it?") fall into one second, and the reading side would consider the
        # second already shown.
        d = os.path.join(tmp, "marks")
        os.makedirs(d)
        marks = []
        for _ in range(2):
            run_bash('ASK_DIR=%s; ask_publish "a question" yn > /dev/null' % d, tmp)
            with open(os.path.join(d, "ask.json"), encoding="utf-8") as fh:
                marks.append(json.load(fh).get("id"))
        check("mark-present", bool(marks[0]), True)
        check("mark-unique", marks[0] != marks[1], True)

        # --- a question does not spoil the capture of a result -------------
        #
        # Half the ask calls stand inside functions that are themselves called as
        # `issue="$(issue_offer …)"`. Everything such a function prints to stdout
        # becomes part of the result — so the prompt and the answer that arrives
        # have to go to stderr, as `read -rp` does.
        #
        # The cost of the mistake is concrete: $issue becomes "Create a GitHub
        # issue? [y/n] 1234", passes the non-empty check, lands in state.json and
        # travels to gh at every step transition.
        d = os.path.join(tmp, "capture")
        os.makedirs(d)
        answer_after(os.path.join(d, "answer.json"), "n", 2)
        out, _, _ = run_bash(
            'ASK_DIR=%s; f(){ ask "Create an issue? [y/n] " a yn; echo "1234"; }; '
            'CAPTURED="$(f)"; echo "[$CAPTURED]"' % d, tmp, stdin="")
        check("prompt-not-captured", out.strip(), "[1234]")

        # --- an answer from the terminal ----------------------------------
        #
        # The way answers have always been given: it must stay as it was.
        d = os.path.join(tmp, "term")
        os.makedirs(d)
        out, _, rc = run_bash(
            'ASK_DIR=%s; ask "Shall we go on? [y/n] " answer yn; rc=$?; '
            'echo "[$answer]"; exit "$rc"' % d, tmp, stdin="y\n")
        check("terminal-reply", out.strip().endswith("[y]"), True)
        check("terminal-rc", rc, 0)
        # A question that has been answered is removed from the channel:
        # otherwise the bot would show buttons for what has already been answered
        # at the laptop.
        check("terminal-retracted", os.path.exists(os.path.join(d, "ask.json")), False)
        # The question leaves a record of how it ended, for the bot to turn
        # its message into the answer (ask_closed).
        closed = os.path.join(d, "closed")
        records = [json.load(open(os.path.join(closed, n), encoding="utf-8"))
                   for n in os.listdir(closed)] if os.path.isdir(closed) else []
        check("terminal-closed-record",
              [(r.get("reply"), r.get("from")) for r in records], [("y", "stdin")])
        check("terminal-closed-id", bool(records and records[0].get("id")), True)

        # A yes/no reply that is neither is not an answer: the question is laid
        # out again, and the chat must lose the old message rather than show it
        # answered with "maybe".
        d = os.path.join(tmp, "refused")
        os.makedirs(d)
        run_bash('ASK_DIR=%s; ask "Go on? [y/n] " answer yn' % d, tmp,
                 stdin="maybe\ny\n")
        closed = os.path.join(d, "closed")
        records = [json.load(open(os.path.join(closed, n), encoding="utf-8"))
                   for n in os.listdir(closed)]
        check("refused-no-record", [r.get("reply") for r in records], ["y"])

        # A number outside a pick:N list is refused and asked again too.
        d_pick = os.path.join(tmp, "pick-refused")
        os.makedirs(d_pick)
        run_bash('ASK_DIR=%s; ask "Which? [1-3] " answer "pick:3"' % d_pick, tmp, stdin="7\n")
        d_pick_ok = os.path.join(tmp, "pick-taken")
        os.makedirs(d_pick_ok)
        run_bash('ASK_DIR=%s; ask "Which? [1-9] " answer "pick:9"' % d_pick_ok, tmp, stdin="08\n")
        d_pick_norm = os.path.join(tmp, "pick-normalized")
        os.makedirs(d_pick_norm)
        out_pick, _, _ = run_bash('ASK_DIR=%s; ask "Which? [1-9] " answer "pick:9"; echo "[$answer]"'
                                  % d_pick_norm, tmp, stdin="08\n")
        check("pick-normalized-for-caller", out_pick.strip().endswith("[8]"), True)
        # Without a channel too.
        out_pick, _, _ = run_bash('unset ASK_DIR; ask "Which? [1-9] " answer "pick:9"; echo "[$answer]"',
                                  tmp, stdin="08\n")
        check("pick-normalized-without-channel", out_pick.strip().endswith("[8]"), True)
        # A number too long for the shell's arithmetic does not wrap into an option.
        d_pick_long = os.path.join(tmp, "pick-long")
        os.makedirs(d_pick_long)
        out_pick, _, _ = run_bash('ASK_DIR=%s; ask "Which? [1-9] " answer "pick:9"; echo "[$answer]"'
                                  % d_pick_long, tmp, stdin="18446744073709551617\n")
        check("pick-overflow-is-no-option", out_pick.strip().endswith("[0]"), True)
        check("pick-overflow-not-recorded",
              os.listdir(os.path.join(d_pick_long, "closed"))
              if os.path.isdir(os.path.join(d_pick_long, "closed")) else [], [])
        # Enter on a list is not shown as an answer: most lists refuse it.
        d_pick_empty = os.path.join(tmp, "pick-empty")
        os.makedirs(d_pick_empty)
        run_bash('ASK_DIR=%s; ask "Which? [1-2] " answer "pick:2"' % d_pick_empty,
                 tmp, stdin="\n")
        check("pick-empty-not-recorded", len(os.listdir(os.path.join(d_pick_empty, "closed")))
              if os.path.isdir(os.path.join(d_pick_empty, "closed")) else 0, 0)
        check("pick-in-range-recorded",
              len(os.listdir(os.path.join(d_pick_ok, "closed")))
              if os.path.isdir(os.path.join(d_pick_ok, "closed")) else 0, 1)
        check("pick-out-of-range-no-record",
              os.listdir(os.path.join(d_pick, "closed")) if os.path.isdir(
                  os.path.join(d_pick, "closed")) else [], [])

        # A week-old record is cleared by the next one: a machine without the
        # bot would otherwise keep them all.
        old_rec = os.path.join(closed, "old.json")
        with open(old_rec, "w") as fh:
            fh.write("{}")
        os.utime(old_rec, (time.time() - 8 * 86400,) * 2)
        fresh_rec = os.path.join(closed, "fresh.json")
        with open(fresh_rec, "w") as fh:
            fh.write("{}")
        os.utime(fresh_rec, (time.time() - 6 * 86400,) * 2)
        # The sweep runs once a day; the questions above have just run it.
        unsweep(d)
        run_bash('ASK_DIR=%s; ask "Again? [y/n] " answer yn' % d, tmp, stdin="n\n")
        check("closed-week-old-pruned", os.path.exists(old_rec), False)
        check("closed-six-days-kept", os.path.exists(fresh_rec), True)

        # --- a feature's own channel ---------------------------------------
        #
        # Features run in parallel; each asks in ask/<slug>/, so that two of
        # them can both reach the phone. A name that is not a plain slug stays
        # in the repository's channel rather than becoming a path.
        d = os.path.join(tmp, "features")
        os.makedirs(d)
        run_bash('ASK_DIR=%s; f(){ local ASK_SLUG=login-fix; ask_publish "q? " yn >/dev/null; }; '
                 'f; ask_publish "repo q? " yn >/dev/null' % d, tmp)
        check("feature-channel",
              json.load(open(os.path.join(d, "ask", "login-fix", "ask.json")))["prompt"], "q? ")
        check("binding-ends-with-function",
              json.load(open(os.path.join(d, "ask.json")))["prompt"], "repo q? ")
        run_bash('ASK_DIR=%s; ASK_SLUG=../x; ask_publish "odd? " yn >/dev/null' % d, tmp)
        check("odd-slug-stays-in-repo-channel",
              json.load(open(os.path.join(d, "ask.json")))["prompt"], "odd? ")

        # Removing the worktree ends the feature for the bot: the record is
        # read while the worktree is there and left in the channel's end mark,
        # and the binding ends with it.
        wt = os.path.join(tmp, "wt")
        os.makedirs(os.path.join(wt, ".sclaude", "local", "feature"))
        with open(os.path.join(wt, ".sclaude", "local", "feature", "telegram.json"), "w") as fh:
            fh.write('{"thread": 5}')
        out, _, _ = run_bash('ASK_DIR=%s; ASK_SLUG=login-fix; r="$(ask_record %s)"; '
                             'ask_feature_end "$r"; echo "[$ASK_SLUG]"' % (d, wt), tmp)
        check("end-mark-carries-record",
              json.load(open(os.path.join(d, "ask", "login-fix", "ended"))), {"thread": 5})
        check("end-unbinds", out.strip(), "[]")
        # An outer function still bound to the feature asks in the repository's
        # channel once the feature has ended.
        out, _, _ = run_bash('ASK_DIR=%s; outer(){ local ASK_SLUG=login-fix; inner; '
                             'ask_channel; }; inner(){ local ASK_SLUG=login-fix; '
                             'ask_feature_end ""; }; outer' % d, tmp)
        check("ended-feature-asks-in-repo", out.strip(), d)
        # A feature of the same name begun later in the same process asks in
        # its own channel again.
        out, _, _ = run_bash('ASK_DIR=%s; ASK_SLUG=again; ask_feature_end ""; '
                             'ASK_SLUG=again; ask_feature_begin; ask_channel' % d, tmp)
        check("begin-after-end-same-process", out.strip(), os.path.join(d, "ask", "again"))
        run_bash('ASK_DIR=%s; ask_feature_end "x"' % d, tmp)
        check("no-feature-no-mark", os.path.exists(os.path.join(d, "ended")), False)

        # drop asks everything before it removes anything: the feature's topic
        # goes with its worktree, and a question after that would have nowhere
        # to go.
        with open(os.path.join(LIB, "abandon.sh"), encoding="utf-8") as fh:
            abandon = fh.read()
        body = abandon[abandon.index("cmd_abandon() {"):]
        body = body[:body.index("\n}\n")]
        check("drop-asks-before-removing",
              body.rindex('ask "') < body.index('remove_worktree "$wt"'), True)
        # Deleting a pull request's head branch closes it on GitHub: the pull
        # request is asked about first, and closed first.
        check("drop-asks-pr-before-origin",
              body.index("Close pull request") < body.index("Delete origin/"), True)
        work = body[body.index("and now the work"):]
        check("drop-keeps-github-when-worktree-stayed",
              'want_tree" -eq 1 && "$wt_gone" -eq 0' in work, True)
        check("drop-closes-pr-before-deleting-origin",
              work.index('want_pr" -eq 1') < work.index('want_origin" -eq 1'), True)

        # code_reload execs into _session-ended from inside a step: the step's
        # last questions must still go to the feature's channel.
        with open(os.path.join(os.path.dirname(LIB), "..", "bin", "sclaude"), encoding="utf-8") as fh:
            sclaude_src = fh.read()
        ended_fn = sclaude_src[sclaude_src.index("cmd_session_ended() {"):]
        ended_fn = ended_fn[:ended_fn.index("\n}\n")]
        check("session-ended-binds-feature", 'local ASK_SLUG="$slug"' in ended_fn, True)

        # A new feature under an ended feature's name clears the old mark; and
        # the week-old sweep never takes a channel with a question open.
        e = os.path.join(tmp, "begin")
        os.makedirs(os.path.join(e, "ask", "foo"))
        open(os.path.join(e, "ask", "foo", "ended"), "w").close()
        run_bash('ASK_DIR=%s; ASK_SLUG=foo; ask_feature_begin' % e, tmp)
        check("begin-sets-old-mark-aside",
              (os.path.exists(os.path.join(e, "ask", "foo", "ended")),
               any(n.startswith("ended-") for n in os.listdir(os.path.join(e, "ask", "foo")))),
              (False, True))
        os.makedirs(os.path.join(e, "ask", "bar"))
        mark = os.path.join(e, "ask", "bar", "ended")
        open(mark, "w").close()
        open(os.path.join(e, "ask", "bar", "ask.json"), "w").close()
        os.utime(mark, (time.time() - 8 * 86400,) * 2)
        unsweep(e)
        run_bash('ASK_DIR=%s; ask_closed abc y tty' % e, tmp)
        check("sweep-spares-open-question", os.path.exists(os.path.join(e, "ask", "bar", "ask.json")), True)

        # A finished feature's channel the bot never cleared goes a week on.
        mark = os.path.join(d, "ask", "login-fix", "ended")
        os.utime(mark, (time.time() - 8 * 86400,) * 2)
        os.unlink(os.path.join(d, "ask", "login-fix", "ask.json"))
        unsweep(d)
        run_bash('ASK_DIR=%s; ask_closed abc y tty' % d, tmp)
        check("ended-channel-pruned",
              os.path.exists(os.path.join(d, "ask", "login-fix")), False)

        # --- an answer from the channel -----------------------------------
        #
        # What the whole thing was for: the human has stepped away from the
        # laptop, the question waits, the answer comes from the phone — and the
        # live process carries on by itself.
        d = os.path.join(tmp, "remote")
        os.makedirs(d)
        answer_after(os.path.join(d, "answer.json"), "y", 2)
        started = time.time()
        out, _, rc = run_bash(
            'ASK_DIR=%s; ask "Shall we go on? [y/n] " answer yn; rc=$?; '
            'echo "[$answer]"; exit "$rc"' % d,
            tmp, stdin="")          # the terminal is silent: stdin is empty
        check("remote-reply", out.strip().endswith("[y]"), True)
        check("remote-rc", rc, 0)
        check("remote-waited", time.time() - started >= 1.5, True)
        check("remote-retracted", os.path.exists(os.path.join(d, "ask.json")), False)
        # The answer is removed too: left behind, it would instantly "answer"
        # the next question — and the human would watch the step skip a question
        # by itself.
        check("remote-answer-cleaned",
              os.path.exists(os.path.join(d, "answer.json")), False)
        closed = os.path.join(d, "closed")
        check("remote-closed-from-channel",
              [json.load(open(os.path.join(closed, n))).get("from")
               for n in os.listdir(closed)], ["channel"])

        # An answer from the phone goes through the same normalisation as one
        # typed by hand: " YES " is a yes once trimmed.
        d = os.path.join(tmp, "remote-upper")
        os.makedirs(d)
        answer_after(os.path.join(d, "answer.json"), " YES ", 1)
        out, _, _ = run_bash(
            'ASK_DIR=%s; ask "Shall we go on? [y/n] " answer yn; '
            'is_yes "$answer" && echo YES || echo NO' % d, tmp, stdin="")
        check("remote-upper-yes", out.strip().endswith("YES"), True)

        # Rubbish from a previous conversation must not answer for the human.
        d = os.path.join(tmp, "stale")
        os.makedirs(d)
        with open(os.path.join(d, "answer.json"), "w", encoding="utf-8") as fh:
            json.dump({"reply": "y"}, fh)
        answer_after(os.path.join(d, "answer.json"), "n", 2)
        out, _, _ = run_bash(
            'ASK_DIR=%s; ask "Shall we go on? [y/n] " answer yn; echo "[$answer]"' % d,
            tmp, stdin="")
        check("stale-answer-dropped", out.strip().endswith("[n]"), True)

        # An answer to the *previous* question must not answer this one.
        #
        # This is not the same case as the one above, and clearing the channel
        # does not cover it. The bot checks that a question is open, and only
        # then writes the answer; between the two the terminal can answer, that
        # question can close and the next one open. The answer then lands on a
        # question the person never saw.
        #
        # It happened in service: "n" to "Ship to production?" arrived as the
        # answer to "Remove all of it?", and a merged feature's worktree and
        # branch were deleted against an explicit refusal. Hence the stamp — the
        # answer carries the id of the question it was given to, and one from
        # another question is discarded.
        # The terminal stays silent here on purpose: the question has to be
        # left standing, so that taking the foreign answer would be the only way
        # it could be answered at all. A real "n" typed at once would win the
        # race by speed and would hide the defect.
        d = os.path.join(tmp, "foreign")
        os.makedirs(d)
        answer_after(os.path.join(d, "answer.json"), "y", 1, ask_id="from-an-older-question")
        # Two seconds of waiting are enough: the foreign answer arrives after
        # one, and the loop goes round every ASK_POLL. If it is taken, the
        # question closes and ask returns; if it is refused, the wait runs out.
        out, _, _ = run_bash(
            'ASK_DIR=%s; ask "Remove all of it? [y/n] " answer yn & '
            'p=$!; sleep 4; kill "$p" 2>/dev/null; '
            'python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get(\'reply\'))" '
            '%s/answer.json 2>/dev/null; '
            '[[ -f %s/ask.json ]] && echo "[still-asking]"' % (d, d, d),
            tmp, stdin="", timeout=25)
        # The question is still in the channel and the foreign answer is still
        # lying there unclaimed: nothing was answered on the person's behalf.
        check("foreign-answer-dropped", "[still-asking]" in out, True)

        # And the stamped answer to *this* question still gets through — the
        # check must refuse the foreign one without refusing every one.
        d = os.path.join(tmp, "stamped")
        os.makedirs(d)

        def stamped_reply(dirname, reply, delay):
            # Reads the id from the question standing in the channel and answers
            # with it, the way the bot does.
            def worker():
                time.sleep(delay)
                with open(os.path.join(dirname, "ask.json"), encoding="utf-8") as fh:
                    ask_id = json.load(fh).get("id") or ""
                tmp_path = os.path.join(dirname, "answer.json.tmp")
                with open(tmp_path, "w", encoding="utf-8") as fh:
                    json.dump({"reply": reply, "id": ask_id}, fh)
                os.replace(tmp_path, os.path.join(dirname, "answer.json"))
            thread = threading.Thread(target=worker)
            thread.daemon = True
            thread.start()

        stamped_reply(d, "y", 2)
        out, _, _ = run_bash(
            'ASK_DIR=%s; ask "Shall we go on? [y/n] " answer yn; echo "[$answer]"' % d,
            tmp, stdin="")
        check("stamped-answer-accepted", out.strip().endswith("[y]"), True)

        # --- when there is nobody to answer -------------------------------
        #
        # Without a channel we must not wait: this is `sclaude status` from the
        # daemon or a call from a pipeline. Telling them from a conversation by
        # inspection is impossible — neither has a terminal — so ASK_DIR decides
        # rather than a guess. The bot calls status with a 25-second timeout, and
        # a question that waits for ever would hang the whole Sclaude section.
        # The previous behaviour: an empty answer and exit code 1.
        started = time.time()
        # We take the exit code straight after ask: any command behind it — the
        # same echo — would set its own, and the check would report success every
        # time.
        out, _, rc = run_bash(
            'unset ASK_DIR; ask "Shall we go on? [y/n] " answer yn; rc=$?; '
            'echo "[$answer]"; exit "$rc"',
            tmp, stdin="", timeout=15)
        check("nobody-returns", out.strip().endswith("[]"), True)
        check("nobody-rc", rc, 1)
        check("nobody-fast", time.time() - started < 5, True)

        # --- the race between two sources ---------------------------------
        #
        # Both answered — the first to arrive wins. Here the terminal answers at
        # once while the channel was going to answer later: the terminal must
        # win.
        d = os.path.join(tmp, "race")
        os.makedirs(d)
        answer_after(os.path.join(d, "answer.json"), "n", 3)
        out, _, _ = run_bash(
            'ASK_DIR=%s; ask "Shall we go on? [y/n] " answer yn; echo "[$answer]"' % d,
            tmp, stdin="y\n")
        check("race-terminal-wins", out.strip().endswith("[y]"), True)

        # --- free text ----------------------------------------------------
        #
        # A feature's name is answered through the channel too: no form is given,
        # but the question is laid out — otherwise a branch's name could not be
        # set from a phone.
        d = os.path.join(tmp, "text")
        os.makedirs(d)
        answer_after(os.path.join(d, "answer.json"), "my-feature", 1)
        out, _, _ = run_bash(
            'ASK_DIR=%s; ask "Feature name: " name; echo "[$name]"' % d, tmp, stdin="")
        check("free-text", out.strip().endswith("[my-feature]"), True)

        # --- the options' labels ------------------------------------------
        #
        # The buttons in a messenger are drawn from options, and without them the
        # choice arrives as digits. We check three cases: the labels are passed,
        # they are not passed at all, and the contract about the form is left
        # untouched in doing so.
        d = os.path.join(tmp, "options")
        os.makedirs(d)
        run_bash(
            'ASK_DIR=%s; ask_publish "Which one? [1-3] " "pick:3" '
            '"Continue" "Sync with main" "Drop the feature" > /dev/null' % d, tmp)
        with open(os.path.join(d, "ask.json")) as fh:
            q = json.load(fh)
        check("options-present", q.get("options"),
              ["Continue", "Sync with main", "Drop the feature"])
        # The form stays as it was: options supplement rather than replace it —
        # otherwise a reading side that knows nothing about labels would stop
        # understanding the question.
        check("options-form-kept", q.get("form"), "pick:3")

        d = os.path.join(tmp, "nooptions")
        os.makedirs(d)
        run_bash('ASK_DIR=%s; ask_publish "Done? [y/n] " "yn" > /dev/null' % d, tmp)
        with open(os.path.join(d, "ask.json")) as fh:
            q = json.load(fh)
        check("options-absent", "options" in q, False)

        # The labels get through via ask as well, not only via a direct
        # ask_publish: that is exactly how the menus pass them.
        d = os.path.join(tmp, "viaask")
        os.makedirs(d)
        answer_after(os.path.join(d, "answer.json"), "2", 1)
        out, _, _ = run_bash(
            'ASK_DIR=%s; ask "Which one? [1-2] " c "pick:2" "First" "Second"; '
            'echo "[$c]"' % d, tmp, stdin="")
        check("options-via-ask", out.strip().endswith("[2]"), True)

        # An empty label among the options would move every following one up by
        # one item: a "Continue" button would answer "Drop the feature". The
        # mistake is not reachable today, but its cost is such that the condition
        # is checked explicitly — the whole list of labels is then not laid out at
        # all, and the buttons arrive as digits, as they did before the whole
        # undertaking.
        d = os.path.join(tmp, "emptyopt")
        os.makedirs(d)
        run_bash(
            'ASK_DIR=%s; ask_publish "Which? [1-3] " "pick:3" "A" "" "C" > /dev/null' % d,
            tmp)
        with open(os.path.join(d, "ask.json")) as fh:
            q = json.load(fh)
        check("an empty label removes the whole list", "options" in q, False)
        check("the form is intact in doing so", q.get("form"), "pick:3")

        total = 67
        for name, want, got in failures:
            print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
        print("%d/%d passed" % (total - len(failures), total))
        return 1 if failures else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
