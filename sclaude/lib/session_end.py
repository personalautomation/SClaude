#!/usr/bin/env python3
#
# What a session's transcript says about its end, for the orchestrator that
# closes it.
#
# A session that believes its work is done writes a marker file and gives its
# report as its last message; the orchestrator then ends the claude process
# itself, so nobody has to type /exit (see session_watch_start in run.sh). Two
# things decide when that may happen, and both are in the transcript:
#
#   * the turn has ended — the report is written in full, not half-streamed;
#   * nobody has typed anything since the marker appeared. A person who answers
#     the report, or runs a command, is still working with the session, and
#     closing it under them would take the conversation away.
#
# And once it is closed, the report itself: the claude screen goes with the
# process, so the orchestrator prints the last message in its own terminal —
# without its advice to type /exit, which by then is already done.
#
#   session_end.py watch <transcript> <since>   → human | ended | working
#   session_end.py watch-plan <transcript> <after> → none | human | ended | working
#   session_end.py approved <transcript>        → when the plan was approved
#   session_end.py last <transcript>            → the last message's text
#   session_end.py first <transcript>           → the text that ended the first
#                                                 turn, before anybody answered
#   session_end.py limit <transcript> [<after>] → the usage limit it stopped on
#
# `since` is seconds since the epoch: the marker's mtime. Silent on any
# trouble — an unreadable transcript is "working" and an empty message.
import datetime
import json
import re
import sys

COMMAND = re.compile(r"<command-name>\s*(/[^<\s]+)")


def entries(path):
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and not entry.get("isSidechain"):
                    yield entry
    except OSError:
        return


def when(entry):
    try:
        moment = datetime.datetime.fromisoformat(
            (entry.get("timestamp") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment.timestamp()


def typed_by_a_person(entry):
    """A prompt a person sent, or a slash command other than /exit.

    Notifications, subagent hand-backs and tool results are user entries too,
    and none of them is somebody at the keyboard: the harness marks a typed
    prompt with origin kind "human". Local commands are system entries whose
    text names the command; /exit is the one that means "close it", which is
    what the orchestrator is about to do anyway.
    """
    if entry.get("type") == "user":
        origin = entry.get("origin") or {}
        return isinstance(origin, dict) and origin.get("kind") == "human"
    if entry.get("type") == "system" and entry.get("subtype") == "local_command":
        found = COMMAND.search(str(entry.get("content") or ""))
        return bool(found) and found.group(1) != "/exit"
    return False


def watch(path, since):
    state = "working"
    for entry in entries(path):
        moment = when(entry)
        if moment is None or moment < since:
            continue
        if typed_by_a_person(entry):
            return "human"
        if entry.get("type") == "assistant":
            reason = (entry.get("message") or {}).get("stop_reason")
            state = "ended" if reason == "end_turn" else "working"
    return state


def watch_plan(path, after):
    """`watch`, counted from the plan's last approval at or after `after`.

    One read of the file for both questions — when the plan was approved, and
    what has happened since — where two processes read it twice. "none" while
    no approval has been given since `after`.
    """
    pending, since, state = False, None, "none"
    for entry in entries(path):
        moment = when(entry)
        for block in (entry.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "ExitPlanMode":
                pending = True
            elif block.get("type") == "tool_result" and pending:
                if "has approved" in str(block.get("content")) \
                        and moment is not None and moment >= after:
                    since, state = moment, "working"
                pending = False
        if since is None or moment is None or moment < since:
            continue
        if typed_by_a_person(entry):
            state = "human"
        elif state != "human" and entry.get("type") == "assistant":
            reason = (entry.get("message") or {}).get("stop_reason")
            state = "ended" if reason == "end_turn" else "working"
    return state


def approved(path):
    """When the plan was last approved: seconds since the epoch, or None.

    Step 1 cannot write a marker — it runs in plan mode, and its hook refuses
    every write, through the shell too. The approval is its marker: the person
    has decided, and what is left is the report. Read the way capture_plan
    reads it (plan.sh): an ExitPlanMode call, and a result after it that says
    the plan was approved.
    """
    pending, moment = False, None
    for entry in entries(path):
        for block in (entry.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "ExitPlanMode":
                pending = True
            elif block.get("type") == "tool_result" and pending:
                if "has approved" in str(block.get("content")):
                    moment = when(entry)
                pending = False
    return moment


def limit(path, after=0):
    """The usage limit the session is standing on, as (entry, resets, kind).

    When the subscription runs out, claude ends the turn with a synthetic
    message — "You've hit your session limit · resets 6:50pm" — and waits for
    somebody to type. Nobody does: on 2026-10-06 #145 and #152 both stopped on
    one at 18:05, the limit reset at 18:50, and both stood until 23:01, when a
    person came back and typed `go` in each.

    The entry carries what is needed as data rather than prose: `error` is
    "rate_limit" and `quotaLimits.resetsAt` the reset in seconds since the
    epoch, with `rateLimitType` saying which limit it was. Anything after it
    that is a turn going on — a person typing, an ordinary assistant message —
    means the session is no longer standing on it. A subagent's own hand-back
    is neither, and does not count.

    `entry` is the message's uuid, so a watcher acts on one limit once;
    `resets` is 0 when the entry did not say. With `after` (seconds since
    the epoch), a limit met before it does not count: a session reopened by
    hand while one still stands at its end is somebody's to carry on, and
    closing it under them because an old reset has passed would take it away.
    """
    hit = None
    for entry in entries(path):
        if typed_by_a_person(entry):
            hit = None
        elif entry.get("type") == "assistant":
            if entry.get("error") == "rate_limit" or entry.get("apiErrorStatus") == 429:
                moment = when(entry)
                if after and moment is not None and moment < after:
                    hit = None
                    continue
                quota = entry.get("quotaLimits") or {}
                try:
                    resets = int(quota.get("resetsAt") or 0)
                except (TypeError, ValueError):
                    resets = 0
                hit = (entry.get("uuid") or "?", resets,
                       quota.get("rateLimitType") or "usage")
            else:
                hit = None
    return hit


def last(path):
    """The text the session wrote after the last thing it was handed.

    A turn interleaves text with tool calls; what the person reads at the end
    is the text after the last tool result or prompt, which is where the
    prompts ask for the report.
    """
    texts = []
    for entry in entries(path):
        kind = entry.get("type")
        if kind == "user":
            texts = []
        elif kind == "assistant":
            for block in (entry.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text" \
                        and (block.get("text") or "").strip():
                    texts.append(block["text"].strip())
    return without_exit("\n\n".join(texts))


def first(path):
    """The text the session wrote at the end of its first turn.

    The retrospective gives its report there and then talks it through with the
    person, so by the time they leave, the last message is about whatever they
    discussed last and the report is further up. The turn ends where somebody
    types the first prompt after the session has said anything.
    """
    texts, spoke = [], False
    for entry in entries(path):
        if spoke and typed_by_a_person(entry):
            break
        kind = entry.get("type")
        if kind == "user":
            texts = []
        elif kind == "assistant":
            for block in (entry.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text" \
                        and (block.get("text") or "").strip():
                    texts.append(block["text"].strip())
                    spoke = True
    return without_exit("\n\n".join(texts))


# A list item: "- ", "* ", "1. " and the like, after any indentation.
ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def without_exit(text):
    """The report with its advice to type /exit taken out.

    Every step's report ends by telling the person to close the session with
    /exit, and by the time sclaude prints it the session is already closed:
    left in, the line asks for something that cannot be done any more. A list
    item that mentions /exit goes whole; in running text only the sentence
    that does. The report is in whatever language the session wrote it, so
    the command itself is what is looked for, not the words around it.
    """
    out = []
    for line in text.split("\n"):
        if "/exit" not in line:
            out.append(line)
            continue
        if ITEM.match(line):
            continue
        kept = " ".join(part for part in SENTENCE_END.split(line.strip())
                        if "/exit" not in part)
        if kept:
            indent = line[:len(line) - len(line.lstrip())]
            out.append(indent + kept)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def main():
    args = sys.argv[1:]
    if len(args) == 3 and args[0] == "watch":
        try:
            since = float(args[2])
        except ValueError:
            since = 0.0
        sys.stdout.write(watch(args[1], since) + "\n")
    elif len(args) == 3 and args[0] == "watch-plan":
        try:
            after = float(args[2])
        except ValueError:
            after = 0.0
        sys.stdout.write(watch_plan(args[1], after) + "\n")
    elif len(args) == 2 and args[0] == "approved":
        moment = approved(args[1])
        if moment is not None:
            sys.stdout.write("%d\n" % int(moment))
    elif len(args) in (2, 3) and args[0] == "limit":
        try:
            after = float(args[2]) if len(args) == 3 else 0.0
        except ValueError:
            after = 0.0
        hit = limit(args[1], after)
        if hit:
            sys.stdout.write("%s %d %s\n" % hit)
    elif len(args) == 2 and args[0] in ("last", "first"):
        text = (last if args[0] == "last" else first)(args[1])
        if text:
            sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
