#!/usr/bin/env python3
#
# Step 2 is accepted in its own session (code.md), not at sclaude's question.
#
# The session ends on one question in its dialog; "Accept" there writes the
# marker, sclaude closes the session and goes on without asking. Guarded here:
#
#   * the header and the accepting label that code.md spells out are the ones
#     session_end.py reads (ACCEPT_HEADER, ACCEPT_LABEL), and the marker word
#     the watcher shortens its grace for is the one code.md writes;
#   * `accepted` says yes for "Accept", no for "Remarks", for free text, for
#     notes beside "Accept", for a person typing after it, and for an answer
#     given before this launch of the session;
#   * `last` prints the report given before the question, not only the line
#     after "Accept";
#   * run.sh records the answer in session_ended as the step's gate, and
#     after_step reads it before its question.
#
# Run it with: python3 tests/code-accept.py
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
END = os.path.join(LIB, "session_end.py")

sys.path.insert(0, LIB)
import session_end  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


with open(os.path.join(ROOT, "sclaude", "prompts", "code.md")) as fh:
    PROMPT = fh.read()
with open(os.path.join(LIB, "run.sh")) as fh:
    RUN = fh.read()

# --- the words both sides share ----------------------------------------------
check("code.md names the header", "header: `%s`" % session_end.ACCEPT_HEADER in PROMPT, True)
check("code.md names the accepting option", "option `%s`" % session_end.ACCEPT_LABEL in PROMPT, True)
check("code.md writes the marker word", "echo accepted > .sclaude/local/feature/session-done" in PROMPT, True)
check("the watcher knows the marker word", '== accepted* ]]' in RUN, True)

# --- transcripts ---------------------------------------------------------------
QUESTION = "Do you accept the work?"


def stamp(second):
    return "2026-10-31T10:00:%02d.000Z" % second


def assistant(second, *blocks):
    return {"type": "assistant", "timestamp": stamp(second),
            "message": {"stop_reason": "tool_use", "content": list(blocks)}}


def text(t):
    return {"type": "text", "text": t}


def ask(qid, header=None):
    return {"type": "tool_use", "id": qid, "name": "AskUserQuestion",
            "input": {"questions": [{"question": QUESTION,
                                     "header": header or session_end.ACCEPT_HEADER}]}}


def answer(second, qid, said, notes=None, header=None):
    result = {"questions": [{"question": QUESTION,
                             "header": header or session_end.ACCEPT_HEADER}],
              "answers": {QUESTION: said}}
    if notes:
        result["annotations"] = {QUESTION: {"notes": notes}}
    return {"type": "user", "timestamp": stamp(second), "toolUseResult": result,
            "message": {"content": [{"type": "tool_result", "tool_use_id": qid,
                                     "content": "answered"}]}}


def bash(second, bid):
    return [assistant(second, {"type": "tool_use", "id": bid, "name": "Bash", "input": {}}),
            {"type": "user", "timestamp": stamp(second),
             "message": {"content": [{"type": "tool_result", "tool_use_id": bid, "content": ""}]}}]


def typed(second, words):
    return {"type": "user", "timestamp": stamp(second), "origin": {"kind": "human"},
            "message": {"content": words}}


def write(entries):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        for e in entries:
            fh.write(json.dumps(e, separators=(",", ":")) + "\n")
    return path


def run(*args):
    return subprocess.run([sys.executable, END] + list(args),
                          capture_output=True, text=True).stdout.strip()


AFTER = str(session_end.when({"timestamp": stamp(0)}))
EARLY = str(session_end.when({"timestamp": stamp(30)}))

base = [assistant(1, text("Report: AC1 done.")), assistant(2, ask("q1"))]
accept = base + [answer(3, "q1", session_end.ACCEPT_LABEL)] + bash(4, "b1") \
    + [assistant(5, text("Accepted."))]

path = write(accept)
check("Accept", run("accepted", path, AFTER), "yes")
check("an answer before this launch", run("accepted", path, EARLY), "no")
check("last keeps the report", run("last", path), "Report: AC1 done.\n\nAccepted.")

check("Accept (Recommended)", run("accepted", write(
    base + [answer(3, "q1", session_end.ACCEPT_LABEL + " (Recommended)")]), AFTER), "yes")
check("Accept with a remark typed", run("accepted", write(
    base + [answer(3, "q1", session_end.ACCEPT_LABEL + " (but the logout is broken)")]), AFTER), "no")
check("Acceptable is not Accept", run("accepted", write(
    base + [answer(3, "q1", session_end.ACCEPT_LABEL + "able")]), AFTER), "no")
check("Remarks", run("accepted", write(base + [answer(3, "q1", "Remarks")]), AFTER), "no")
check("free text", run("accepted", write(base + [answer(3, "q1", "the button is red")]), AFTER), "no")
check("notes beside Accept",
      run("accepted", write(base + [answer(3, "q1", session_end.ACCEPT_LABEL, "one thing")]), AFTER), "no")
check("typed after Accept", run("accepted", write(accept + [typed(6, "wait")]), AFTER), "no")
check("another question", run("accepted", write(
    [assistant(1, ask("q1", "Scope"))] + [answer(2, "q1", session_end.ACCEPT_LABEL, header="Scope")]), AFTER), "no")
check("accepted again after remarks", run("accepted", write(
    base + [answer(3, "q1", "Remarks"), typed(4, "fix it"),
            assistant(5, text("Fixed.")), assistant(6, ask("q2")),
            answer(7, "q2", session_end.ACCEPT_LABEL)]), AFTER), "yes")
check("no question at all", run("accepted", write([assistant(1, text("Report."))]), AFTER), "no")

# A report after remarks, no answer yet: the report is the last message.
path = write(base + [answer(3, "q1", "Remarks"), typed(4, "fix it"), assistant(5, text("Fixed."))])
check("last after remarks", run("last", path), "Fixed.")

# A later launch opens on sclaude's own message: the old report is not carried.
# (Claude Code marks that message as typed: origin kind human.)
opening = typed(20, "Carry on.")
check("last after a new launch", run("last", write(accept + [opening, assistant(21, text("New."))])), "New.")
# A notification before the close is not a new turn.
note = {"type": "user", "timestamp": stamp(6), "origin": {"kind": "task-notification"},
        "message": {"content": "<task-notification>done</task-notification>"}}
check("last past a notification", run("last", write(accept + [note])), "Report: AC1 done.")

# --- run.sh wiring --------------------------------------------------------------
ended = RUN[RUN.index("\nsession_ended() {"):]
ended = ended[:ended.index("\n}\n")]
check("session_ended records the answer", 'code_accepted "$wt" "$session"' in ended, True)
check("the answer sets the gate",
      bool(re.search(r'code_accepted "\$wt" "\$session"; then\n\s*state_set "\$state" "steps\.\$step\.gate" true\n\s*fi', ended)), True)
after = RUN[RUN.index("\nafter_step() {"):]
after = after[:after.index("\n}\n")]
read_at = after.find('elif [[ "$(state_get "$state" "steps.$step.gate"')
asked_at = after.find("Do you confirm that everything works")
check("after_step reads the answer before its question", 0 <= read_at < asked_at, True)
code_at = after.find("no_change_feature")
early_at = after.find('[[ "$gate_only" == "gate" ]] || extend_acceptance "$wt"\n')
late_at = after.find('      extend_acceptance "$wt" reworded\n      ;;')
check("the criteria are written as the session ends, before the yes is read",
      0 < early_at < read_at, True)
check("and again before the step closes, after step 2's regression, never holding it",
      0 < code_at < after.find("regression_gate", code_at) < late_at
      < after.find('step_run "$wt" "$step" close'), True)
check("code_accepted is defined", bool(re.search(r"^code_accepted\(\) \{", RUN, re.M)), True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
