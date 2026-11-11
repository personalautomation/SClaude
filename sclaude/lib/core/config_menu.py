#!/usr/bin/env python3
#
# The `config` screen of sclaude's menu: every section of the project's
# .sclaude/config.json, what it holds now and what it is for.
#
# The explanations are not written here. They are the README of
# sclaude/config.example.json, section by section, so the screen and the file
# a person copies say the same thing and are changed in one place.
#
#   config_menu.py rows <config> <example>         key<TAB>summary, one per section
#   config_menu.py show <config> <example> <key>   the explanation and the value
#   config_menu.py choices <key>                   value<TAB>meaning, for a key
#                                                  the screen can set itself
#   config_menu.py default <key>                   what an absent key means
#   config_menu.py set <config> <key> <value>      write one such value, for
#                                                  this machine (below)
#   config_menu.py mine <config> <key>             this machine's choice, or 1
#   config_menu.py recommended <config> <key>      the committed file's choice
#   config_menu.py effective <config>              the whole, with this machine's
#                                                  choices over it, as JSON
#
# Only a section with fixed choices is set from the screen; the rest are
# structures (commands, environments, a database) that the screen shows and the
# person edits in the file. A setter for those would be a second, worse editor.
#
# The committed .sclaude/config.json holds what the project recommends. A
# choice set from the screen (or the bot, through `sclaude config set`) is this
# machine's and goes to .sclaude/local/config.json beside it, which git and
# every upload are kept out of (scratch.sh), and wins over the committed one
# key by key (project_get in project.sh). Written into the committed file, such
# an edit was a change in main's working tree that origin lacked, and
# production stopped on it (prod_main_unready in vercel.sh) until somebody
# pushed the person's taste to the whole team or threw it away. A choice set
# back to what the project recommends leaves the local file.
import json
import os
import re
import sys

# The sections a person can set from the screen, with what each value means.
# The first is what an absent key means, unless DEFAULTS says otherwise.
CHOICES = {
    "review": [
        ("github", "the review workflow in GitHub Actions: runner minutes and its token; "
                   "step 4 stops when it cannot run"),
        ("github-local", "the review workflow in GitHub Actions, and when it cannot run "
                         "(Claude's limit, no Actions minutes) the feature moves to the review here"),
        ("local", "sclaude runs /code-review on this machine, your Claude account; "
                  "the repository's Actions workflows are switched off"),
        ("off", "no review; step 4 answers only the checks and people"),
    ],
    "qa": [
        ("github", "QA moves the issue to Done on the board; sclaude waits"),
        ("both", "the same, or press a in the wait: sclaude ticks every "
                 "criterion and moves the issue itself"),
        ("auto", "nobody is waited for: a green preview is accepted at once"),
    ],
    "merge": [
        ("github", "the pull request is merged on GitHub; sclaude waits"),
        ("both", "the same, or sclaude asks, and m in the wait merges from here"),
        ("auto", "nobody is waited for: merged once QA passed and GitHub allows it"),
    ],
}

CHOICES["sleep_mode"] = [
    ("auto", "step 4 goes on by itself, as [g] does, while an /isleep night "
             "over every session is on (not /isleep here)"),
    ("on", "step 4 always goes on by itself"),
    ("off", "only where [g] is ticked by hand"),
]

# The regression each deployed stage runs (project_stage_regression in
# project.sh) and whether the merge goes on to production (project_ship_mode).
for _stage, _when in (("preview", "against the preview, before QA"),
                      ("prod", "against production, after the ship")):
    CHOICES[_stage + "Regression"] = [
        ("full", "the stage's whole list in `regression`, " + _when),
        ("smoke", "only `regression.smoke`, the product's few vital paths "
                  "(the whole list where it declares none)"),
        ("none", "no regression at this stage, and no gate"),
    ]

CHOICES["ship"] = [
    ("ask", "after the merge sclaude asks: Ship to production? [y/n]"),
    ("auto", "shipped without the question; still asked when QA or a check "
             "was passed over, or other features' code rides along"),
    ("off", "sclaude never deploys to production; the issue closes as merged"),
]

CHOICES["demo"] = [
    ("on", "step 2 records a demo video of the feature before its question, and "
           "it is brought up to the code before QA (with qa auto, before the "
           "last epilogue)"),
    ("off", "no demo videos: the report and the criteria are the check"),
]

CHOICES["demoVoice"] = [
    ("on", "a recorded demo is spoken: each step's line and each scenario's "
           "card, in English, by a model on this machine's CPU (~350 MB, once)"),
    ("off", "the demo videos are silent; the captions say it all"),
]

CHOICES["partAccept"] = [
    ("whole", "a feature built in parts is shown once, whole, when every part "
              "is built; the parts' reviews follow"),
    ("each", "each part's session ends on its demo and the Accept question, "
             "and the whole is accepted again at the end"),
]

CHOICES["metricsTeam"] = [
    ("real", "the metrics page compares the people whose work is in the records"),
    ("demo", "three generated teammates beside them, drawn from the real figures, "
             "to show the page with a team"),
]

# An absent key that means something other than its first choice: the merge
# sclaude offered before `merge` existed.
DEFAULTS = {"merge": "both"}


def default(key):
    return DEFAULTS.get(key) or (CHOICES[key][0][0] if key in CHOICES else "")

# A README line that opens a section: its key, a run of spaces, a dash.
SECTION = re.compile(r"^([a-z][a-zA-Z_]*)\s+— (.*)$")


def explanations(example):
    """{key: explanation} from the example's README, in its order."""
    try:
        with open(example, encoding="utf-8") as fh:
            readme = json.load(fh).get("README") or []
    except (OSError, ValueError):
        return {}
    found, key = {}, None
    for line in readme:
        match = SECTION.match(line)
        if match:
            key = match.group(1)
            found[key] = [match.group(2)]
        elif key and line.strip():
            found[key].append(line.strip())
        elif key:
            key = None
    return {k: " ".join(v) for k, v in found.items()}


def load(config):
    try:
        with open(config, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def summary(key, value):
    """The value in a few words, for the row."""
    if value is None:
        return default(key) + " (not set)" if key in CHOICES else "not set"
    if isinstance(value, str):
        return value
    if key == "regression" and isinstance(value, dict):
        return " · ".join("%s: %d" % (k, len(v) if isinstance(v, list) else 0)
                          for k, v in value.items())
    if key == "manuals" and isinstance(value, list):
        return ", ".join(m.get("path", "?") if isinstance(m, dict) else str(m) for m in value)
    if key == "database" and isinstance(value, dict):
        return value.get("migrations") or "%d keys" % len(value)
    if key == "doctor" and isinstance(value, list):
        return "%d check(s)" % len(value)
    if isinstance(value, dict):
        return ", ".join(value)
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or "empty"
    return json.dumps(value)


def first_sentence(text):
    end = text.find(". ")
    return text if end < 0 else text[:end + 1]


def local_path(config):
    """This machine's choices: .sclaude/local/config.json beside the
    committed .sclaude/config.json."""
    return os.path.join(os.path.dirname(config), "local", "config.json")


def overrides(config):
    """{key: value} of the choices set for this machine alone — only keys
    with choices, and only values the key can take: a stray structure or a
    word nobody offers there is not read."""
    found = load(local_path(config)) or {}
    return {k: v for k, v in found.items()
            if k in CHOICES and v in [c for c, _ in CHOICES[k]]}


def unreadable(config):
    """True when the committed file is there and does not read as a config."""
    return load(config) is None and os.path.exists(config)


def effective(config):
    """The committed config with this machine's choices over it — over
    nothing when the committed file does not read, as project_get still
    reads them then."""
    data = dict(load(config) or {})
    data.update(overrides(config))
    return data


def recommended(config, key):
    """What the committed config says for a key, or what its absence means."""
    value = (load(config) or {}).get(key)
    return value if isinstance(value, str) else default(key)


MINE = " (this machine)"


def rows(config, example):
    data = effective(config)
    mine = overrides(config)
    known = explanations(example)
    for key, text in known.items():
        print("%s\t%s%s — %s" % (key, summary(key, data.get(key)), MINE if key in mine else "",
                                 first_sentence(text)))
    # A section sclaude does not describe: shown, so the screen is the whole
    # file, but nothing reads it.
    for key in data:
        if key not in known:
            print("%s\t%s — not a section sclaude reads" % (key, summary(key, data[key])))


def show(config, example, key):
    data = effective(config)
    print(explanations(example).get(key, "No explanation for %s." % key))
    print()
    if key in data:
        print("Now:")
        print(json.dumps(data[key], indent=2, ensure_ascii=False))
    else:
        print("Not set in %s." % config)
    if key in overrides(config):
        print("Set on this machine, in %s; the project recommends %s."
              % (local_path(config), recommended(config, key)))


def choices(key):
    for value, meaning in CHOICES.get(key, []):
        print("%s\t%s" % (value, meaning))


def set_value(config, key, value):
    """The choice for this machine, in local_path(config); the key leaves it
    when the value is what the project recommends."""
    if value not in [v for v, _ in CHOICES.get(key, [])]:
        sys.stderr.write("%s cannot be %r\n" % (key, value))
        return 1
    if unreadable(config):
        # What the project recommends cannot be told, so neither can whether
        # this choice is the person's own: nothing changes until it is fixed.
        sys.stderr.write("cannot read %s as JSON; not changed\n" % config)
        return 1
    mine = local_path(config)
    data = load(mine)
    if data is None:
        if os.path.exists(mine):
            sys.stderr.write("cannot read %s as JSON; not changed\n" % mine)
            return 1
        data = {}
    if value == recommended(config, key):
        data.pop(key, None)
    else:
        data[key] = value
    os.makedirs(os.path.dirname(mine) or ".", exist_ok=True)
    with open(mine, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return 0


def main(argv):
    if len(argv) >= 3 and argv[0] == "rows":
        rows(argv[1], argv[2])
    elif len(argv) >= 4 and argv[0] == "show":
        show(argv[1], argv[2], argv[3])
    elif len(argv) >= 2 and argv[0] == "choices":
        choices(argv[1])
    elif len(argv) >= 2 and argv[0] == "default":
        print(default(argv[1]))
    elif len(argv) >= 3 and argv[0] == "mine":
        # This machine's choice for a key, for project_get; 1 when none.
        mine = overrides(argv[1])
        if argv[2] not in mine:
            return 1
        print(mine[argv[2]])
    elif len(argv) >= 2 and argv[0] == "effective":
        # The config as sclaude reads it on this machine, for a session's copy.
        # 1 when the committed file does not read: the caller hands the
        # session that file as it is, so that it sees what is wrong.
        if unreadable(argv[1]):
            return 1
        print(json.dumps(effective(argv[1]), indent=2, ensure_ascii=False))
    elif len(argv) >= 3 and argv[0] == "recommended":
        print(recommended(argv[1], argv[2]))
    elif len(argv) >= 4 and argv[0] == "set":
        return set_value(argv[1], argv[2], argv[3])
    else:
        sys.stderr.write(__doc__ or "usage: see the header of config_menu.py\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
