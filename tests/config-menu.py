#!/usr/bin/env python3
#
# The `config` screen (sclaude/lib/core/config.sh, config_menu.py): every section of
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
MENU = os.path.join(LIB, "core", "config_menu.py")

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

    # A choice set is this machine's: .sclaude/local/config.json, outside
    # git, while the committed file keeps what the project recommends — an
    # edit there stopped production until somebody pushed it to the team.
    local = os.path.join(tmp, "repo", ".sclaude", "local", "config.json")
    with open(config) as fh:
        committed = fh.read()
    rc, _ = menu("set", config, "review", "off")
    check("set-rc", rc, 0)
    with open(config) as fh:
        check("set-leaves-committed", fh.read(), committed)
    with open(local) as fh:
        check("set-value-local", json.load(fh), {"review": "off"})
    check("mine", menu("mine", config, "review"), (0, "off\n"))
    check("recommended", menu("recommended", config, "review")[1].strip(), "local")
    rows = dict(line.split("\t", 1) for line in menu("rows", config, EXAMPLE)[1].splitlines())
    check_true("row-marks-this-machine", rows["review"].startswith("off (this machine) — "))
    check_true("show-says-recommended", "the project recommends local" in menu("show", config, EXAMPLE, "review")[1])
    script = 'source "%s/core/project.sh"; REPO=%s; project_review_mode' % (LIB, os.path.join(tmp, "repo"))
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.strip()
    check("project-get-reads-local", out, "off")
    rc, _ = menu("set", config, "review", "sometimes")
    check("set-refuses-unknown-value", rc, 1)
    rc, _ = menu("set", config, "commands", "x")
    check("set-refuses-structure", rc, 1)
    with open(local) as fh:
        check("refused-not-written", json.load(fh)["review"], "off")
    # Back to the recommendation: nothing of this machine's own is left.
    rc, _ = menu("set", config, "review", "local")
    with open(local) as fh:
        check("set-back-clears", (rc, json.load(fh)), (0, {}))
    check("mine-none", menu("mine", config, "review")[0], 1)
    # A stray structure or a word nobody offers in the local file is not read.
    write(local, {"review": "sometimes", "commands": {"lint": "x"}})
    check("stray-not-mine", (menu("mine", config, "review")[0], menu("mine", config, "commands")[0]), (1, 1))
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.strip()
    check("stray-not-read", out, "local")
    os.remove(local)

    # A file that is not JSON is never overwritten.
    os.makedirs(os.path.dirname(local), exist_ok=True)
    with open(local, "w") as fh:
        fh.write("{broken")
    rc, _ = menu("set", config, "review", "off")
    check("broken-not-overwritten", rc, 1)
    with open(local) as fh:
        check("broken-kept", fh.read(), "{broken")
    os.remove(local)
    # Nor is anything written while the committed file does not read: what
    # the project recommends cannot be told.
    with open(config, "w") as fh:
        fh.write("{broken")
    check("committed-broken-refused", menu("set", config, "review", "off")[0], 1)
    check("committed-broken-nothing-local", os.path.exists(local), False)
    check("effective-broken-fails", menu("effective", config)[0], 1)
    # This machine's choices still show over a broken committed file, as
    # project_get still reads them.
    write(local, {"review": "off"})
    with open(config, "w") as fh:
        fh.write("{broken")
    rows = dict(l.split("\t", 1) for l in menu("rows", config, EXAMPLE)[1].splitlines())
    check_true("broken-rows-keep-mine", rows["review"].startswith("off (this machine)"))
    os.remove(local)
    # The copy a retrospective reads: the committed file with this machine's
    # choices over it.
    write(config, {"review": "local", "commands": {"lint": "x"}})
    write(local, {"review": "off"})
    check("effective", json.loads(menu("effective", config)[1]),
          {"review": "off", "commands": {"lint": "x"}})
    os.remove(local)

    # The main checkout's choice outranks the one a feature's tree carries.
    repo = os.path.join(tmp, "repo")
    wt = os.path.join(tmp, "wt")
    write(config, {"review": "local"})
    write(os.path.join(wt, ".sclaude", "config.json"), {"review": "off"})
    script = 'source "%s/core/project.sh"; REPO=%s; project_review_mode %s' % (LIB, repo, wt)
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.strip()
    check("main-checkout-first", out, "local")
    write(config, {})
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.strip()
    check("tree-when-main-has-none", out, "off")

    # sleep_mode: auto, on, off — absent or unknown is auto, so a night still
    # drives the review where nobody chose; its README line names a row.
    check("sleep-choices", [l.split("\t")[0] for l in menu("choices", "sleep_mode")[1].splitlines()],
          ["auto", "on", "off"])
    sleep = 'source "%s/core/project.sh"; REPO=%s; project_sleep_mode %s' % (LIB, repo, wt)
    for value, want in (("off", "off"), ("on", "on"), ("asleep", "auto"), (None, "auto")):
        write(config, {} if value is None else {"sleep_mode": value})
        out = subprocess.run(["bash", "-c", sleep], capture_output=True, text=True).stdout.strip()
        check("sleep-mode-%s" % value, out, want)
    write(config, {})
    rows = dict(l.split("\t", 1) for l in menu("rows", config, EXAMPLE)[1].splitlines())
    check_true("sleep-row-explained", "goes on by itself" in rows.get("sleep_mode", ""))
    rc, _ = menu("set", config, "sleep_mode", "on")
    check("sleep-set-rc", rc, 0)
    with open(local) as fh:
        check("sleep-set", json.load(fh).get("sleep_mode"), "on")
    os.remove(local)

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
        script = 'source "%s/core/project.sh"; REPO=%s; project_flow_mode qa; project_flow_mode merge' % (LIB, repo)
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.split()
        check("flow-mode-%s" % (value or "absent"), out,
              [want, "both" if want == "github" else want])
    # The flow and the screen agree on what an absent key means: the defaults
    # live in two files, and this is what ties them.
    write(config, {})
    script = 'source "%s/core/project.sh"; REPO=%s; project_flow_mode qa; project_flow_mode merge' % (LIB, repo)
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.split()
    check("flow-default-is-the-screen-default", out,
          [menu("default", "qa")[1].strip(), menu("default", "merge")[1].strip()])

    # `sclaude config set`, which the bot's menu calls: the same write as the
    # screen's, and review's Actions follow it.
    write(config, {"review": "github"})
    script = ('LIB=%s; source "$LIB/core/config.sh"; REPO=%s; GREEN=; OFF=\n'
              'say() { echo "S:$*"; }; info() { :; }; warn() { echo "W:$*"; }\n'
              'require_repo() { :; }; die() { echo "D:$*"; exit 1; }\n'
              'review_actions_sync() { echo "SYNC:$2"; }\n'
              'scratch_hide() { echo "HIDE:$1"; }\n'
              'cmd_config "$@"') % (LIB, repo)
    out = subprocess.run(["bash", "-c", script, "bash", "set", "review", "local"],
                         capture_output=True, text=True)
    check("set-writes", json.load(open(local)).get("review"), "local")
    check("set-leaves-the-project-file", json.load(open(config)).get("review"), "github")
    check_true("set-says-this-machine", "on this machine" in out.stdout)
    check_true("set-hides-the-local-file-first", "HIDE:%s" % repo in out.stdout)
    check_true("set-syncs-actions", "SYNC:local" in out.stdout)
    check("set-exit", out.returncode, 0)
    out = subprocess.run(["bash", "-c", script, "bash", "set", "review", "maybe"],
                         capture_output=True, text=True)
    check("set-refuses-a-stranger", (out.returncode, json.load(open(local)).get("review")),
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
