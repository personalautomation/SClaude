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
#   config_menu.py set <config> <key> <value>      write one such value
#
# Only a section with fixed choices is set from the screen; the rest are
# structures (commands, environments, a database) that the screen shows and the
# person edits in the file. A setter for those would be a second, worse editor.
import json
import os
import re
import sys

# The sections a person can set from the screen, with what each value means.
# The first is what an absent key means.
CHOICES = {
    "review": [
        ("github", "the review workflow in GitHub Actions: runner minutes and its token"),
        ("local", "sclaude runs /code-review on this machine, your Claude account"),
        ("off", "no review; step 4 answers only the checks and people"),
    ],
}

# A README line that opens a section: its key, a run of spaces, a dash.
SECTION = re.compile(r"^([a-z][a-zA-Z]*)\s+— (.*)$")


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
        return CHOICES[key][0][0] + " (not set)" if key in CHOICES else "not set"
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


def rows(config, example):
    data = load(config) or {}
    known = explanations(example)
    for key, text in known.items():
        print("%s\t%s — %s" % (key, summary(key, data.get(key)), first_sentence(text)))
    # A section sclaude does not describe: shown, so the screen is the whole
    # file, but nothing reads it.
    for key in data:
        if key not in known:
            print("%s\t%s — not a section sclaude reads" % (key, summary(key, data[key])))


def show(config, example, key):
    data = load(config) or {}
    print(explanations(example).get(key, "No explanation for %s." % key))
    print()
    if key in data:
        print("Now:")
        print(json.dumps(data[key], indent=2, ensure_ascii=False))
    else:
        print("Not set in %s." % config)


def choices(key):
    for value, meaning in CHOICES.get(key, []):
        print("%s\t%s" % (value, meaning))


def set_value(config, key, value):
    if value not in [v for v, _ in CHOICES.get(key, [])]:
        sys.stderr.write("%s cannot be %r\n" % (key, value))
        return 1
    data = load(config)
    if data is None:
        if os.path.exists(config):
            sys.stderr.write("cannot read %s as JSON; not changed\n" % config)
            return 1
        data = {}
    data[key] = value
    os.makedirs(os.path.dirname(config) or ".", exist_ok=True)
    with open(config, "w", encoding="utf-8") as fh:
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
    elif len(argv) >= 4 and argv[0] == "set":
        return set_value(argv[1], argv[2], argv[3])
    else:
        sys.stderr.write(__doc__ or "usage: see the header of config_menu.py\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
