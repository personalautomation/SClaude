#!/usr/bin/env python3
#
# The `config` screen (sclaude/lib/config.sh, config_menu.py): every section of
# the project's .sclaude/config.json with its value and its explanation.
#
# Guarded here:
#
#   * the explanations come from sclaude/config.example.json's README, and every
#     section that README describes gets a row — a section added to the README
#     appears on the screen without a second text to keep in step;
#   * a section the file holds that sclaude does not read is shown too;
#   * only a section with fixed choices is set, only to one of them, and the
#     rest of the file survives the write;
#   * the review mode is read from the main checkout before a feature's tree.
#
# Run it with: python3 tests/config-menu.py
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
EXAMPLE = os.path.join(ROOT, "sclaude", "config.example.json")
MENU = os.path.join(LIB, "config_menu.py")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


def menu(*args):
    out = subprocess.run([sys.executable, MENU] + list(args), capture_output=True, text=True)
    return out.returncode, out.stdout


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(data, fh)


tmp = tempfile.mkdtemp()
try:
    config = os.path.join(tmp, "repo", ".sclaude", "config.json")
    write(config, {"commands": {"lint": "npm run lint"}, "regression": {"local": ["lint"]},
                   "review": "local", "extra": 1})

    with open(EXAMPLE) as fh:
        example = json.load(fh)
    # Every top-level key of the example but the README is a section the
    # README must explain, or it would be missing from the screen.
    sections = [k for k in example if k != "README"]

    rc, out = menu("rows", config, EXAMPLE)
    keys = [line.split("\t")[0] for line in out.splitlines()]
    check("rows-rc", rc, 0)
    for key in sections:
        check_true("row-for-" + key, key in keys)
    check_true("row-for-unknown", "extra" in keys)
    rows = dict(line.split("\t", 1) for line in out.splitlines())
    check_true("review-row-value", rows["review"].startswith("local — "))
    check_true("commands-row-value", rows["commands"].startswith("lint — "))
    check_true("unset-row", rows["manuals"].startswith("not set — "))
    check_true("unknown-row-says-so", "not a section sclaude reads" in rows["extra"])

    rc, out = menu("show", config, EXAMPLE, "review")
    check_true("show-explains", "no-review" in out and '"local"' in out)

    rc, out = menu("choices", "review")
    check("review-choices", [l.split("\t")[0] for l in out.splitlines()],
          ["github", "local", "off"])
    rc, out = menu("choices", "commands")
    check("structure-has-no-choices", out, "")

    rc, _ = menu("set", config, "review", "off")
    check("set-rc", rc, 0)
    with open(config) as fh:
        data = json.load(fh)
    check("set-value", data["review"], "off")
    check("set-keeps-rest", data["commands"], {"lint": "npm run lint"})
    rc, _ = menu("set", config, "review", "sometimes")
    check("set-refuses-unknown-value", rc, 1)
    rc, _ = menu("set", config, "commands", "x")
    check("set-refuses-structure", rc, 1)
    with open(config) as fh:
        check("refused-not-written", json.load(fh)["review"], "off")

    # A file that is not JSON is never overwritten.
    with open(config, "w") as fh:
        fh.write("{broken")
    rc, _ = menu("set", config, "review", "local")
    check("broken-not-overwritten", rc, 1)
    with open(config) as fh:
        check("broken-kept", fh.read(), "{broken")

    # The main checkout's choice outranks the one a feature's tree carries.
    repo = os.path.join(tmp, "repo")
    wt = os.path.join(tmp, "wt")
    write(config, {"review": "local"})
    write(os.path.join(wt, ".sclaude", "config.json"), {"review": "off"})
    script = 'source "%s/project.sh"; REPO=%s; project_review_mode %s' % (LIB, repo, wt)
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.strip()
    check("main-checkout-first", out, "local")
    write(config, {})
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.strip()
    check("tree-when-main-has-none", out, "off")

    # sleep_mode: auto, on, off — absent or unknown is auto, so a night still
    # drives the review where nobody chose; its README line names a row.
    check("sleep-choices", [l.split("\t")[0] for l in menu("choices", "sleep_mode")[1].splitlines()],
          ["auto", "on", "off"])
    sleep = 'source "%s/project.sh"; REPO=%s; project_sleep_mode %s' % (LIB, repo, wt)
    for value, want in (("off", "off"), ("on", "on"), ("asleep", "auto"), (None, "auto")):
        write(config, {} if value is None else {"sleep_mode": value})
        out = subprocess.run(["bash", "-c", sleep], capture_output=True, text=True).stdout.strip()
        check("sleep-mode-%s" % value, out, want)
    write(config, {})
    rows = dict(l.split("\t", 1) for l in menu("rows", config, EXAMPLE)[1].splitlines())
    check_true("sleep-row-explained", "goes on by itself" in rows.get("sleep_mode", ""))
    rc, _ = menu("set", config, "sleep_mode", "on")
    check("sleep-set-rc", rc, 0)
    with open(config) as fh:
        check("sleep-set", json.load(fh).get("sleep_mode"), "on")

    # qa and merge: three words each; an absent merge is the offer sclaude
    # made before the key existed.
    for key in ("qa", "merge"):
        rc, out = menu("choices", key)
        check("%s-choices" % key, [l.split("\t")[0] for l in out.splitlines()],
              ["github", "both", "auto"])
    check("qa-default", menu("default", "qa")[1].strip(), "github")
    check("merge-default", menu("default", "merge")[1].strip(), "both")
    write(config, {})
    rows = dict(l.split("\t", 1) for l in menu("rows", config, EXAMPLE)[1].splitlines())
    check_true("merge-row-default", rows.get("merge", "").startswith("both (not set)"))
    check_true("qa-row-explained", "who accepts" in rows.get("qa", ""))
    for value, want in (("", "github"), ("auto", "auto"), ("sometimes", "github")):
        write(config, {"qa": value, "merge": value} if value else {})
        script = 'source "%s/project.sh"; REPO=%s; project_flow_mode qa; project_flow_mode merge' % (LIB, repo)
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.split()
        check("flow-mode-%s" % (value or "absent"), out,
              [want, "both" if want == "github" else want])
    # The flow and the screen agree on what an absent key means: the defaults
    # live in two files, and this is what ties them.
    write(config, {})
    script = 'source "%s/project.sh"; REPO=%s; project_flow_mode qa; project_flow_mode merge' % (LIB, repo)
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.split()
    check("flow-default-is-the-screen-default", out,
          [menu("default", "qa")[1].strip(), menu("default", "merge")[1].strip()])

    # `sclaude config set`, which the bot's menu calls: the same write as the
    # screen's, and review's Actions follow it.
    write(config, {"review": "github"})
    script = ('LIB=%s; source "$LIB/config.sh"; REPO=%s; GREEN=; OFF=\n'
              'say() { echo "S:$*"; }; info() { :; }; warn() { echo "W:$*"; }\n'
              'require_repo() { :; }; die() { echo "D:$*"; exit 1; }\n'
              'review_actions_sync() { echo "SYNC:$2"; }\n'
              'cmd_config "$@"') % (LIB, repo)
    out = subprocess.run(["bash", "-c", script, "bash", "set", "review", "local"],
                         capture_output=True, text=True)
    check("set-writes", json.load(open(config)).get("review"), "local")
    check_true("set-syncs-actions", "SYNC:local" in out.stdout)
    check("set-exit", out.returncode, 0)
    out = subprocess.run(["bash", "-c", script, "bash", "set", "review", "maybe"],
                         capture_output=True, text=True)
    check("set-refuses-a-stranger", (out.returncode, json.load(open(config)).get("review")),
          (1, "local"))
    check_true("set-refusal-does-not-sync", "SYNC" not in out.stdout)
    out = subprocess.run(["bash", "-c", script, "bash", "set", "review"],
                         capture_output=True, text=True)
    check_true("set-needs-both", out.returncode != 0 and "D:usage" in out.stdout)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
