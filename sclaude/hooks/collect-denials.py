#!/usr/bin/env python3
#
# Refusals a hook does not see: they are issued by Claude Code itself rather
# than by our ban.
#
# The step's bans are caught by forbidden-commands.py, which writes them to the
# log itself, from the hook. But in auto mode a command is also judged by the
# built-in classifier, and its refusal passes by: Claude Code has no hook for
# such an event at all — PostToolUse fires only after a successful call, and
# there is no separate "permission denied". Verified on 2.1.258.
#
# That is how three refusals in one feature's step 4 were
# lost: reading the log of someone else's CI run, and checking YAML for
# validity. The log stayed empty, the session took a detour, and it was found
# only because a human read the transcript by hand — precisely the work the log
# was created to abolish.
#
# Hence the transcript parsing here. _friction.py says there is no reason to
# parse it, and when that was written it was true: we searched for the word
# "denied", and it occurs more often in the model's own text than in refusals.
# Now we search for a field rather than a word: a refusal entry has
# toolDenialKind, and it answers precisely.
#
# The kinds of refusal that occur in the field (counted across 206 transcripts):
#
#   automode-blocked      auto mode's classifier — what this file exists for
#   automode-unavailable  the classifier did not answer (the model is
#                         overloaded); the step stalled not on a ban but on the
#                         judge being unavailable
#   permission-rule       --disallowed-tools and our hooks. The hook has already
#                         written this itself, from deny() — we take such
#                         entries only when the text is not ours, otherwise the
#                         log would double up
#   user-rejected         the human refused by hand. That is not friction from a
#                         tool but the human's decision, and it does not belong
#                         in the log
#
# The transcript's format is Claude Code's internal business and changes between
# versions, so the parsing is written to stay quiet rather than fall over: no
# file, changed fields, drifted JSON — we return an empty list. An empty log
# costs a feature's review; a crashed orchestrator costs the feature itself.
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _friction import note
from _shell import SEPARATORS, call_form, strip_runners, strip_wrappers, tokenize

# The refusals that reach the log, and how their source is named in the entry.
# user-rejected is deliberately not here: a human who refused by hand is not
# friction from a tool.
KINDS = {
    "automode-blocked": "classifier",
    "automode-unavailable": "classifier",
    "permission-rule": "rule",
}

# The tails our hooks append to their reasons: TAIL and the other endings from
# forbidden-commands.py,
# the ending of REASON from no-code-in-planning.py, and TAIL from
# plan-on-disk.py. We recognise our own refusals by them — the first
# two hooks have already written those, and a second time is not wanted; the
# third is a gate doing its job (a plan without acceptance criteria), not a
# restriction that got in the way.
#
# The strings duplicate the hooks' text, and an edit there requires an edit
# here: the comparison goes through the transcript, where only the text of the
# reason survives. The second marker sat here with a typo from an earlier
# revision and matched nothing — that is what the test further down the list is
# for.
OWN_MARKERS = (
    "Tell the human and stop — the next move is theirs.",
    "tell the human and stop.",
    "Then present the plan again.",
    "Then carry on with the step's own work.",
    "Write it more plainly, as separate calls, and carry on.",
)
# The write guard's refusals are not among them: it writes nothing to the
# log itself, so a refusal of its own, one getting in the way of real work
# included, reaches the review only from here.


# Deliberate bans, already reviewed once: sclaude/known-denials.txt.
#
# The device is the same as OWN_MARKERS above, but the reason differs. There we
# do not write what the hook has already written itself; here, what there is no
# longer any reason to write: a refusal on `vercel` or `gh pr merge` is
# permanent by construction, and the friction review issues the same verdict on
# it every feature. The log dies with the worktree, and only the repository can
# remember this — which is why the list lives in it.
def known_denials():
    """The substrings from the list of deliberate bans. No file, empty list."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.pardir, "known-denials.txt")
    out = []
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return out
    with handle:
        for line in handle:
            # A comment both trailing and at the start of a line: in the list
            # an explanation stands next to the command, which is what the list
            # is a text file for.
            line = line.split("#", 1)[0].strip()
            if line:
                out.append(line)
    return out


def policy_denials(step=""):
    """The bans the session's policy made: deliberate by construction.

    A product's own bans (`npm run db:promote` and the like) and its
    integrations' are written in its .sclaude/team/ and in sclaude's presets;
    a refusal of one is that rule working, not friction. Read for the product
    whose worktree this is (CLAUDE_PROJECT_DIR) and the person in
    SCLAUDE_POLICY_PERSON, at this step: a step's own bans (`gh pr create`
    on step 2) are among them. Nothing on any trouble.

    Returns the banned command prefixes, as word tuples, and the banned tools.
    The prefixes are compared with the commands the call ran, not searched for
    in its text: a bare `vercel` found in any subject used to drop every
    refusal that mentioned Vercel, the reads the hook allows among them.
    """
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        os.pardir, "lib"))
        import subprocess
        import policy
        tree = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute",
                                 "--git-common-dir"], cwd=tree, capture_output=True,
                                text=True, timeout=5)
        if common.returncode != 0:
            return [], []
        # The tree's own rules too: a friction review commits them there.
        merged = policy.merged(os.path.dirname(common.stdout.strip()),
                               os.environ.get("SCLAUDE_POLICY_PERSON", ""), step, tree)
    except Exception:
        return [], []
    return ([tuple(call_form(list(d["words"]))) for d in merged["deny"]],
            list(merged["tools"]))


def runs_banned(subject, prefixes, tools):
    """Whether the call in this subject is one of the policy's bans."""
    name, _, rest = subject.partition(": ")
    if name in tools:
        return True
    if name != "Bash" or not prefixes:
        return False
    words = tokenize(rest) or []
    part = []
    for word in words + [";"]:
        if word not in SEPARATORS:
            part.append(word)
            continue
        called = call_form(strip_runners(strip_wrappers(part)))
        if any(tuple(called[:len(p)]) == p for p in prefixes):
            return True
        part = []
    return False


def denial_reason(result):
    """The refusal's text from toolUseResult, or None if it is not a refusal."""
    if isinstance(result, str):
        return trim(result)
    if isinstance(result, dict):
        for key in ("error", "message", "stderr"):
            value = result.get(key)
            if isinstance(value, str) and value:
                return trim(value)
    return None


# The classifier's refusal is eight lines, of which seven are the same in every
# refusal: how to carry on and that the ban must not be worked around. The
# analysis needs the first; it has already read the rest in the previous entry.
# We cut on known phrases rather than by length: that way everything survives
# from an unforeseen text.
CHATTER = (
    " If you have other tasks that don't depend on this action",
    " IMPORTANT: You *may* attempt",
    " Note: reading files, searching code",
)


def trim(text):
    """The reason without the tail of instructions, identical from one refusal
    to the next."""
    cut = len(text)
    for phrase in CHATTER:
        found = text.find(phrase)
        if found != -1:
            cut = min(cut, found)
    return text[:cut].strip()


def tool_calls(path):
    """A call's id -> what tool it was and what it was called with.

    A refusal arrives as a separate entry and names only tool_use_id, so we look
    for the command in the call that preceded it.
    """
    calls = {}
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return calls
    with handle:
        for line in handle:
            if '"tool_use"' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            content = (entry.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                data = block.get("input") or {}
                subject = ""
                if isinstance(data, dict):
                    for key in ("command", "file_path", "pattern", "url"):
                        value = data.get(key)
                        if isinstance(value, str) and value:
                            subject = value
                            break
                calls[block.get("id")] = "%s: %s" % (block.get("name") or "?",
                                                     subject or "—")
    return calls


def denials(path, step=""):
    """The refusals from a transcript: a list of (source, subject, reason)."""
    calls = tool_calls(path)
    wont_note = known_denials()
    prefixes, tools = policy_denials(step)
    out = []
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return out
    with handle:
        for line in handle:
            if "toolDenialKind" not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            source = KINDS.get(entry.get("toolDenialKind"))
            if not source:
                continue
            reason = denial_reason(entry.get("toolUseResult"))
            if not reason:
                continue
            # Our own refusal, already written by the hook at the moment it
            # happened.
            if any(marker in reason for marker in OWN_MARKERS):
                continue
            subject = ""
            content = (entry.get("message") or {}).get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        subject = calls.get(block.get("tool_use_id"), "")
                        break
            # A deliberate ban, reviewed once: there is nothing to review
            # again, and this entry would cost a whole session.
            if any(known in subject for known in wont_note) \
                    or runs_banned(subject, prefixes, tools):
                continue
            out.append((source, subject or "—", reason))
    return out


def main(argv):
    if len(argv) < 2:
        return 0
    step, paths = argv[0], argv[1:]
    for path in paths:
        # The rules the session ran under, when not its step's own (a sync
        # runs under the review step's, sync.sh).
        for source, subject, reason in denials(path, os.environ.get("SCLAUDE_POLICY_STEP") or step):
            note(step, source, subject, reason)
    return 0


if __name__ == "__main__":
    # The orchestrator calls this between steps and does not look at the return
    # code: gathering statistics is no reason to stop a feature's cycle.
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:
        sys.exit(0)
