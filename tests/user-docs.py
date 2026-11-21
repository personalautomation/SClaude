#!/usr/bin/env python3
#
# What a user can set or run is explained in the guides the wiki is built
# from. A setting or a command the code takes and no guide names is one
# nobody can find out about, so this fails on one.
#
# docs/config.md — every key of a product's .sclaude/config.json:
# - every key of sclaude/config.example.json (the names of environments and
#   of database.local.env's variables are the product's own, so their
#   attributes are checked instead of them);
# - every section its README explains (`name — …`);
# - every key a `project_get` or `project_value` in the shell names;
# - every choice in CHOICES (config_menu.py), with each of its values in the
#   page's table of choices.
#
# docs/sclaude-guide.md — every command bin/sclaude dispatches, as
# `sclaude <command>` (the internal ones, `_name`, aside).
#
# Run it with: python3 tests/user-docs.py
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "sclaude", "lib", "core"))
import config_menu  # noqa: E402

failures = []


def check(name, ok, detail=""):
    if not ok:
        failures.append((name, detail))


with open(os.path.join(ROOT, "docs", "config.md")) as fh:
    page = fh.read()


def named(key):
    """The page names a key as code (`key`, or "key" in an example) or in a
    heading of its own."""
    return (("`%s`" % key) in page or ('"%s"' % key) in page
            or re.search(r"^#+ .*\b%s\b" % re.escape(key), page, re.M) is not None)


# --- the example ---------------------------------------------------------------
with open(os.path.join(ROOT, "sclaude", "config.example.json")) as fh:
    example = json.load(fh)

OWN_NAMES = {"environments", "database.local.env"}


def walk(node, path):
    for key, value in node.items():
        dotted = path + "." + key if path else key
        if dotted == "README":
            continue
        if path in OWN_NAMES:
            # The product's own name: its attributes are what is explained.
            if isinstance(value, dict):
                for attr in value:
                    check("example %s.<name>.%s" % (path, attr), named(attr))
            continue
        check("example key %s" % dotted, named(key))
        if isinstance(value, dict):
            walk(value, dotted)


walk(example, "")

# --- the sections the example's README explains ------------------------------
for line in example["README"]:
    m = re.match(r"^([A-Za-z_]\w*)\s+—", line)
    if m:
        check("README section %s" % m.group(1), named(m.group(1)))
    for key in re.findall(r"\b(?:cli|copyFromMain|teardown|sweep|envLink|envKeys|buildCache|testRunner|deps|deploy)\b", line):
        check("README key %s" % key, named(key))

# --- what the code reads --------------------------------------------------------
READ = re.compile(r"""project_(?:get|value)\s+(?:"[^"]*config\.json"\s+)?["']?([A-Za-z_][\w.:-]*)["']?""")
seen = set()
for top in ("sclaude", "bin", "skills"):
    for base, _dirs, files in os.walk(os.path.join(ROOT, top)):
        for name in files:
            path = os.path.join(base, name)
            try:
                with open(path) as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            # The shell reads the config through these two; Python opens the
            # file itself, and its prose mentions them.
            if not (name.endswith(".sh") or text.startswith("#!/usr/bin/env bash")):
                continue
            for line in text.splitlines():
                code = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
                for key in READ.findall(code):
                    if key.startswith(("$", "-")) or key in ("path", "key"):
                        continue
                    seen.add(key)
check("the code's reads were found", len(seen) > 20, sorted(seen))
for key in sorted(seen):
    check("read by the code: %s" % key, named(key.split(".")[-1]), key)

# --- the choices ----------------------------------------------------------------
rows = {}
for line in page.splitlines():
    m = re.match(r"^\| `([A-Za-z_]+)` \|(.*)\|(.*)\|$", line)
    if m:
        rows[m.group(1)] = m.group(2)
for key, choices in config_menu.CHOICES.items():
    check("choice %s in the table" % key, key in rows)
    check("choice %s has its own section" % key,
          ("### " + key) in page or re.search(r"^### .*\b%s\b" % re.escape(key), page, re.M))
    for value, _what in choices:
        check("choice %s: %s" % (key, value), ("`%s`" % value) in rows.get(key, ""))

# --- the commands ---------------------------------------------------------------
with open(os.path.join(ROOT, "bin", "sclaude")) as fh:
    src = fh.read()
dispatch = src[src.index("    new)"):src.index("    -h|--help|help)")]
commands = re.findall(r"^    ([a-z][a-z-]*)(?:\|[a-z-]+)*\)", dispatch, re.M)
check("the commands were found", len(commands) > 20, commands)
with open(os.path.join(ROOT, "docs", "sclaude-guide.md")) as fh:
    guide = fh.read()
for command in commands:
    check("command %s in the guide" % command,
          re.search(r"sclaude %s\b" % re.escape(command), guide) is not None)

if failures:
    for name, detail in failures:
        sys.stderr.write("FAIL %s%s\n" % (name, ("\n  " + str(detail)) if detail else ""))
    sys.stderr.write("\n%d failure(s)\n" % len(failures))
    sys.exit(1)
print("ok")
