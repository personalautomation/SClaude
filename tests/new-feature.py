#!/usr/bin/env python3
#
# How a feature starts when its answers come with it: the branch name an issue
# suggests (sclaude/lib/github/issue_list.py, which bin/sclaude's suggest_slug and the
# bot's Mini App both use) and `sclaude new`'s options (new_from_args).
#
# Guarded here:
#
#   * the suggestion keeps the rules the terminal had: four words at most,
#     40 characters, no trailing article, the number alone for a title with
#     no Latin word;
#   * suggest_slug in bin/sclaude prints the same as the module;
#   * each option reaches cmd_new as the answer it stands for, a name alone
#     still goes to cmd_new, and nothing at all to the picker;
#   * the picker's `config` opens the settings and comes back to the picker,
#     and the menu with no feature in progress asks the picker for that row.
#
# Run it with: python3 tests/new-feature.py
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
SCLAUDE = os.path.join(ROOT, "bin", "sclaude")
sys.path.insert(0, LIB)
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
from issue_list import slugify, suggest  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


CASES = [
    ((42, "Change an account how"), "42-change-an-account"),
    ((42, "Fix the login page on mobile safari now"), "42-fix-the-login-page"),
    ((42, "Как сделать"), "issue-42"),
    ((42, "Add support for the new API"), "42-add-support"),
    ((7, "supercalifragilisticexpialidocious-extraordinarily long"),
     "7-supercalifragilisticexpialidocious"),
    ((12345, "a the of"), "12345-a"),
]
for (number, title), want in CASES:
    check("suggest %r" % title, suggest(number, title), want)
check("slugify", slugify("  Dark Mode: v2! "), "dark-mode-v2")
# ASCII only, as bin/sclaude's: the page checks the branch sclaude will make.
check("slugify leaves non-ASCII out", slugify("İzmir Kelvin\u212a"), "zmir-kelvin")


def function(name):
    """One function of bin/sclaude or the modules its commands live in, by
    its text: the file runs its main when sourced."""
    body = ""
    for path in (SCLAUDE, os.path.join(LIB, "commands", "start.sh"), os.path.join(LIB, "commands", "menu.sh")):
        with open(path) as fh:
            body += fh.read()
    m = re.search(r"^%s\(\) \{\n.*?^\}\n" % re.escape(name), body, re.S | re.M)
    return m.group(0) if m else ""


for (number, title), want in CASES:
    out = subprocess.run(["bash", "-c", 'LIB=%s\n%s\nsuggest_slug "$1" "$2"'
                          % (LIB, function("suggest_slug")), "bash", str(number), title],
                         capture_output=True, text=True).stdout.strip()
    check("suggest_slug %r" % title, out, want)

bash_slug = subprocess.run(["bash", "-c", '%s\nslugify "$1"' % function("slugify"), "bash",
                            "İzmir Kelvin\u212a"], capture_output=True, text=True).stdout.strip()
check("as bash does", bash_slug, "zmir-kelvin")
for name in ("-n", "-e", "-ne"):
    out = subprocess.run(["bash", "-c", '%s\nslugify "$1"' % function("slugify"), "bash", name],
                         capture_output=True, text=True).stdout.strip()
    check("bash slugify of %s, as the page has it" % name, out, slugify(name))

ARGS = ('%s\ndie() { echo "DIE:$*"; exit 1; }\n'
        'cmd_new() { echo "NEW name=$1 issue=$2 create=$NEW_CREATE_ISSUE ok=$NEW_BLOCKED_OK${3:+ title=$3}"; }\n'
        'start_feature() { echo PICKER; }\n'
        'gh_repo() { echo o/r; }\n'
        'gh() { [[ "$*" == "issue view 61 -R o/r --json title -q .title" ]] && echo Alpha; }\n'
        'new_from_args "$@"') % function("new_from_args")


def new(*args):
    return subprocess.run(["bash", "-c", ARGS, "bash"] + list(args),
                          capture_output=True, text=True).stdout.strip()


check("nothing is the picker", new(), "PICKER")
check("a name alone", new("dark-mode"), "NEW name=dark-mode issue= create= ok=")
check("from an issue, its blockers seen",
      new("--issue", "61", "--blocked-ok", "61-alpha"),
      "NEW name=61-alpha issue=61 create= ok=1")
check("an issue without a name gets its title for the suggestion", new("--issue", "61"),
      "NEW name= issue=61 create= ok= title=Alpha")
check("a name with an issue made", new("--create-issue", "Dark mode"),
      "NEW name=Dark mode issue= create=yes ok=")
check("a name with none", new("--no-issue", "x"), "NEW name=x issue= create=no ok=")
check("words not quoted together are one name", new("dark", "mode"),
      "NEW name=dark mode issue= create= ok=")
check("a name after -- may start with a dash", new("--no-issue", "--", "-x"),
      "NEW name=-x issue= create=no ok=")
check("--issue takes a number", new("--issue", "abc"), "DIE:--issue takes a number")
check("an unknown option stops", new("--yes", "x"), "DIE:sclaude new: unknown option --yes")

# start_feature: the settings come back to the picker, which then decides;
# the issues are fetched once for all of it, and a failed fetch is said once.
# pick_start runs in $( ), so which answer it gives next is counted in a file.
START = ('%s\ninfo() { echo "INFO:$*"; }\n'
         'DIM=""; OFF=""\n'
         'person_at_terminal() { true; }\n'
         'gh() { :; }\n'
         'fetch_issues() { echo FETCH >&2; [[ -z "$FAIL" ]] && printf "1\\t61\\tAlpha\\n"; }\n'
         'cmd_config() { echo CONFIG; }\n'
         'cmd_new() { echo "NEW $*"; }\n'
         'answers=("$@")\n'
         'pick_start() {\n'
         '  local n; n="$(cat "$COUNT")"; echo $((n + 1)) > "$COUNT"\n'
         '  echo "GIVEN:${1%%%%$\'\\t\'*}" >&2\n'
         '  [[ "${answers[$n]}" == q ]] && return 1\n'
         '  printf "%%b\\n" "${answers[$n]}"\n'
         '}\n'
         'PICK_START_CONFIG=$CONFIG start_feature') % function("start_feature")


def start(*answers, fail="", config="1"):
    with tempfile.NamedTemporaryFile("w+") as count:
        count.write("0")
        count.flush()
        done = subprocess.run(["bash", "-c", START, "bash"] + list(answers),
                              capture_output=True, text=True,
                              env=dict(os.environ, COUNT=count.name, FAIL=fail, CONFIG=config))
        return done.stdout.split(), done.stderr.splitlines()


out, err = start("config", "issue\\t61\\tAlpha")
check("config, then an issue", out, ["CONFIG", "NEW", "61", "Alpha"])
check("the issues fetched once, given to every picker", err, ["FETCH", "GIVEN:1", "GIVEN:1"])
check("config, then cancelled", start("config", "q")[0], ["CONFIG", "INFO:Cancelled."])
check("a name by hand", start("manual")[0], ["NEW"])
check("a failed fetch is said once, the picker given nothing",
      start("config", "manual", fail="1")[1],
      ["FETCH", "Could not fetch the issue list.", "GIVEN:", "GIVEN:"])
# Without the settings (`sclaude new`, the menu's "new feature"), the same
# fetch, and the failure says the name is asked next.
out, err = start("manual", fail="1", config="")
check("no settings: a failed fetch, then the name", (out, err),
      (["NEW"], ["FETCH", "Could not fetch the issue list — starting the feature by name.",
                 "GIVEN:"]))
check("no settings: the issues fetched and given", start("manual", config="")[1],
      ["FETCH", "GIVEN:1"])

# The menu with no feature in progress hands start_feature the settings row.
MENU = ('%s\nrequire_repo() { :; }\nlist_features() { :; }\n'
        'review_branches() { :; }\nprod_drift_report() { :; }\n'
        'offer_epilogues() { :; }\ninfo() { :; }\n'
        'start_feature() { echo "START config=${PICK_START_CONFIG:-} env=$(printenv PICK_START_CONFIG)"; }\n'
        'cmd_menu\necho "AFTER config=${PICK_START_CONFIG:-}"') % function("cmd_menu")
check("the empty menu asks the picker for its config row",
      subprocess.run(["bash", "-c", MENU], capture_output=True, text=True).stdout.split(),
      ["START", "config=1", "env=", "AFTER", "config="])

for name, want, got in failures:
    print("FAIL %s: want %r, got %r" % (name, want, got))
if failures:
    sys.exit(1)
print("ok")
