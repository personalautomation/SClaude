#!/usr/bin/env python3
# The cycle's steps, once: their order, how each one's session is launched,
# the icon each opens its lines with, and what the bot calls them.
#
# Before, the same list stood in five places — STEPS and STEP_SPEC in
# steps.sh, the step icons in phase_icon, PHASE_ICONS in the bot's
# notices.py, the step names in i18n's act.steps, the count in the issue's
# summary — kept in step by tests/session_names.py. Now they read it here.
#
# The shell does not start python to read it: cycle_steps.sh, beside this
# file, is written from it (`python3 cycle_steps.py sh > cycle_steps.sh`) and
# committed, and tests/session_names.py fails when it is not what this file
# writes. A step added here is added to the shell's by running that.

# The four steps a feature's state goes through, in order (`step` in the
# state, STEPS in the shell). model, effort and mode are its session's
# launch; title is how the menu names it ("2/7 development"). What the bot
# calls each place is in its i18n.py, by the place's name (`cycle.<name>`):
# the bot's words in two languages stay there.
STEPS = [
    dict(name="plan", model="opus", effort="high", mode="plan", title="planning",
         icon="📝"),
    dict(name="code", model="opus", effort="medium", mode="auto", title="development",
         icon="💻"),
    dict(name="pr", model="sonnet", effort="medium", mode="auto", title="pull request",
         icon="📤"),
    dict(name="review", model="opus", effort="medium", mode="auto", title="review",
         icon="🛠"),
]

# The sessions after them that the cycle numbers on (cycle_number): the
# sync with main, the epilogue after the merge, the retrospective last.
AFTER = [
    dict(name="sync", icon="🔀"),
    dict(name="epilogue", icon="🏁"),
    dict(name="retro", icon="🔁"),
]

# The icons of the other kinds of line (phase_icon): a step's session of
# no known step, a step closed, and the sessions and runs around the steps.
KINDS = [
    ("step", "▶️"),
    ("done", "✅"),
    ("friction", "🧱"),
    ("deferred", "🧱"),
    ("fix", "🔧"),
    ("local-review", "🔍"),
    ("regression", "🧪"),
    ("deploy", "🚀"),
]


def total():
    """The steps the menu counts: the four and the three after them."""
    return len(STEPS) + len(AFTER)


def icons():
    """Every icon a line of sclaude's may open with, each once, the steps'
    own first (the bot's PHASE_ICONS)."""
    out = []
    for icon in [s["icon"] for s in STEPS] + [i for _, i in KINDS] + [a["icon"] for a in AFTER]:
        if icon not in out:
            out.append(icon)
    return tuple(out)


def places():
    """The cycle's seven places, in order: the four steps and the three after."""
    return [s["name"] for s in STEPS + AFTER]


def shell():
    """cycle_steps.sh: the same table as the shell's arrays."""
    def q(text):
        return "'" + text.replace("'", "'\\''") + "'"
    lines = [
        "# shellcheck shell=bash",
        "# Written by cycle_steps.py (`python3 cycle_steps.py sh > cycle_steps.sh`):",
        "# change that file, not this one. tests/session_names.py checks the two agree.",
        "# Sourced by steps.sh.",
        "",
        "STEPS=(%s)" % " ".join(s["name"] for s in STEPS),
        "AFTER_STEPS=(%s)" % " ".join(a["name"] for a in AFTER),
        "# model effort mode|title (step_field)",
        "declare -gA STEP_SPEC=(",
    ]
    for s in STEPS:
        lines.append("  [%s]=%s" % (s["name"], q("%s %s %s|%s" % (s["model"], s["effort"], s["mode"], s["title"]))))
    lines += [")", "declare -gA PHASE_ICON=("]
    for s in STEPS:
        lines.append("  [step-%s]=%s" % (s["name"], q(s["icon"])))
    for kind, icon in KINDS:
        lines.append("  [%s]=%s" % (kind, q(icon)))
    for a in AFTER:
        lines.append("  [%s]=%s" % (a["name"], q(a["icon"])))
    lines.append(")")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["sh"]:
        sys.stdout.write(shell())
    else:
        sys.exit("usage: cycle_steps.py sh > cycle_steps.sh")
