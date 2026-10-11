#!/usr/bin/env python3
#
# Every feature's own dev server port, and the registry sclaude-proxy reads.
#
# What is at stake: two features started together must never be handed one
# port — that is how one feature's browser and e2e end up on another's code,
# silently and green — and a feature must keep its port and its address between
# runs, or a bookmark and a running session both lose it.
#
# Run it with: python3 tests/ports.py
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")

failures = []
total = 0


def check(name, got, want):
    global total
    total += 1
    if got != want:
        failures.append((name, want, got))


def bash(root, body, env=None):
    script = """
set -uo pipefail
info() { :; }
warn() { echo "WARN $*" >&2; }
GREEN=""; OFF=""
REPO="%s/repo"
source "%s/state.sh"
source "%s/worktree.sh"
DEV_PORT_FIRST=%d
DEV_PORT_LAST=%d
%s
""" % (root, LIB, LIB, FIRST, LAST, body)
    full = dict(os.environ)
    full.pop("DEV_PORT", None)
    full["SCLAUDE_DEV_REGISTRY"] = os.path.join(root, "registry")
    full["HOME"] = root
    if env:
        full.update(env)
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env=full, timeout=60)
    return done.stdout.strip()


def free_block(size):
    """A run of ports nobody on this machine is listening on."""
    for base in range(41000, 60000, 50):
        ok = True
        for port in range(base, base + size):
            with socket.socket() as s:
                try:
                    s.bind(("127.0.0.1", port))
                except OSError:
                    ok = False
                    break
        if ok:
            return base
    raise SystemExit("no free block of ports for the test")


FIRST = free_block(20)
LAST = FIRST + 19


def tree(root, name, feature=None, extra=None):
    wt = os.path.join(root, name)
    os.makedirs(os.path.join(wt, ".feature"), exist_ok=True)
    data = {"feature": feature or name, "step": "code"}
    data.update(extra or {})
    with open(os.path.join(wt, ".feature", "state.json"), "w") as fh:
        json.dump(data, fh)
    return wt


def state(wt):
    with open(os.path.join(wt, ".feature", "state.json")) as fh:
        return json.load(fh)


def main():
    root = tempfile.mkdtemp(prefix="sclaude-ports-")
    try:
        os.makedirs(os.path.join(root, "repo"))
        registry = os.path.join(root, "registry")

        a = tree(root, "a", "71-email-edit")
        port_a = bash(root, 'feature_port "%s"' % a)
        check("first claim is in the range", port_a.isdigit()
              and FIRST <= int(port_a) <= LAST, True)
        check("the port is recorded", state(a)["dev"]["port"], int(port_a) if port_a.isdigit() else None)
        check("the label is the slug", state(a)["dev"]["label"], "71-email-edit")
        check("the rest of the state is kept", state(a)["step"], "code")
        check("the proxy's link points at the tree",
              os.path.realpath(os.path.join(registry, "71-email-edit")), os.path.realpath(a))
        check("a second call keeps the port", bash(root, 'feature_port "%s"' % a), port_a)
        check("the address is the label under the proxy",
              bash(root, 'feature_url "%s"' % a), "http://71-email-edit.localhost:3000")

        b = tree(root, "b")
        port_b = bash(root, 'feature_port "%s"' % b)
        check("another tree gets another port", port_b != port_a and port_b.isdigit(), True)

        # A port recorded by another tree is taken even while its server is not
        # running: the next start of that feature expects it.
        c = tree(root, "c")
        port_c = bash(root, 'feature_port "%s"' % c)
        check("recorded ports are skipped, not only listening ones",
              port_c not in (port_a, port_b), True)

        # A port something is listening on is skipped.
        taken = FIRST + 10
        with socket.socket() as held:
            held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            held.bind(("127.0.0.1", taken))
            held.listen(1)
            got = []
            for i in range(8):
                got.append(bash(root, 'feature_port "%s"' % tree(root, "fill%d" % i)))
            if shutil.which("ss"):
                check("a listening port is skipped", str(taken) in got, False)

        # Asked to move off a port, a tree gets a different one and keeps its
        # label.
        before = state(b)["dev"]["port"]
        bash(root, 'dev_claim "%s" %d' % (b, before))
        check("avoid gives a new port", state(b)["dev"]["port"] != before, True)
        check("avoid keeps the label", state(b)["dev"]["label"], "b")

        # The same slug in two trees: the second does not take the first's
        # link.
        other = tree(root, "other-a", "71-email-edit")
        bash(root, 'feature_port "%s"' % other)
        check("a clashing label gets a suffix", state(other)["dev"]["label"], "71-email-edit-2")
        check("the first tree keeps its link",
              os.path.realpath(os.path.join(registry, "71-email-edit")), os.path.realpath(a))

        # What a DNS name allows.
        odd = tree(root, "odd", "Foo_Bar--Baz " + "x" * 80)
        bash(root, 'feature_port "%s"' % odd)
        label = state(odd)["dev"]["label"]
        check("the label is a DNS label", label.startswith("foo-bar-baz-x")
              and len(label) <= 63 and not label.endswith("-"), True)

        # The main repository is `main`.
        repo = os.path.join(root, "repo")
        bash(root, 'feature_port "%s"' % repo)
        check("the main repository is main", state(repo)["dev"]["label"], "main")

        # A pinned port wins and touches nothing.
        pinned = tree(root, "pinned")
        check("DEV_PORT wins", bash(root, 'feature_port "%s"' % pinned, {"DEV_PORT": "4000"}), "4000")
        check("DEV_PORT records nothing", "dev" in state(pinned), False)
        check("DEV_PORT gives the port straight",
              bash(root, 'feature_url "%s"' % pinned, {"DEV_PORT": "4000"}), "http://localhost:4000")

        # Claims made at the same moment do not collide.
        root2 = tempfile.mkdtemp(prefix="sclaude-ports-race-")
        try:
            os.makedirs(os.path.join(root2, "repo"))
            trees = [tree(root2, "r%d" % i) for i in range(6)]
            body = "\n".join('feature_port "%s" >/dev/null &' % t for t in trees) + "\nwait"
            bash(root2, body)
            ports = [state(t).get("dev", {}).get("port") for t in trees]
            check("parallel claims get distinct ports",
                  len(set(ports)) == len(ports) and None not in ports, True)
        finally:
            shutil.rmtree(root2, ignore_errors=True)

        # A link to a tree that is gone is cleared by the next claim.
        gone = tree(root, "gone")
        bash(root, 'feature_port "%s"' % gone)
        shutil.rmtree(gone)
        bash(root, 'dev_claim "%s"' % a)
        check("a dead link is cleared", os.path.islink(os.path.join(registry, "gone")), False)

        # The proxy is asked once and the answer kept, in a file, since most
        # callers are $(…) subshells. Port 1: nothing listens.
        check("a proxy that does not answer is down",
              bash(root, 'proxy_up && echo up || echo down', {"SCLAUDE_PROXY_PORT": "1"}), "down")
        check("the answer is kept for the next subshell",
              open(os.path.join(registry, ".proxy-up")).read().strip(), "down")

        # stop_dev removes the tree's link — both its callers remove the tree.
        bash(root, 'stop_dev "%s"' % c)
        check("stop_dev unregisters", os.path.islink(os.path.join(registry, "c")), False)
        # And marks the tree as closing, so neither the proxy nor ensure_dev
        # brings a server back while git deletes it. In feature 40 a browser
        # left open on the feature did exactly that, and the new server wrote
        # .dev-build into the tree mid-removal.
        check("stop_dev marks the tree as closing",
              os.path.exists(os.path.join(c, ".feature", "closing")), True)
        npm_stub = os.path.join(root, "npm-stub")
        os.makedirs(npm_stub)
        with open(os.path.join(npm_stub, "npm"), "w") as fh:
            fh.write("#!/bin/sh\ntouch \"$HOME/closing-npm-ran\"\n")
        os.chmod(os.path.join(npm_stub, "npm"), 0o755)
        bash(root, 'ensure_dev "%s"' % c,
             {"PATH": npm_stub + os.pathsep + os.environ["PATH"]})
        check("ensure_dev starts nothing in a closing tree",
              os.path.exists(os.path.join(root, "closing-npm-ran")), False)
        check("ensure_dev registers nothing for a closing tree",
              os.path.islink(os.path.join(registry, "c")), False)

        # remove_worktree: a file written after git deleted the tree and
        # dropped it from its list is a leftover, and goes. A tree git still
        # lists — here a locked one, which --force alone will not remove — is
        # work, and stays.
        g = os.path.join(root, "git-repo")
        quiet = {"capture_output": True, "check": True}
        subprocess.run(["git", "init", "-q", "-b", "main", g], **quiet)
        subprocess.run(["git", "-C", g, "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "--allow-empty", "-m", "init"], **quiet)
        late = os.path.join(root, "wt-late")
        subprocess.run(["git", "-C", g, "worktree", "add", "-q", "-b", "late", late], **quiet)
        subprocess.run(["git", "-C", g, "worktree", "remove", late], **quiet)
        os.makedirs(os.path.join(late, ".feature"))
        with open(os.path.join(late, ".dev-build"), "w") as fh:
            fh.write("{}\n")
        check("remove_worktree clears what was written after git's removal",
              bash(root, 'REPO="%s"; remove_worktree "%s" && echo ok' % (g, late)), "ok")
        check("and the directory is gone", os.path.exists(late), False)
        locked = os.path.join(root, "wt-locked")
        subprocess.run(["git", "-C", g, "worktree", "add", "-q", "-b", "locked", locked], **quiet)
        subprocess.run(["git", "-C", g, "worktree", "lock", locked], **quiet)
        check("remove_worktree refuses a tree git still lists",
              bash(root, 'REPO="%s"; remove_worktree "%s" 2>/dev/null || echo refused'
                   % (g, locked)), "refused")
        check("and leaves it in place", os.path.isdir(locked), True)

        # Reinstalling dependencies stops this tree's server and drops the
        # Turbopack cache. In feature 104 both survived the reinstall, and every
        # page failed on a module path into the old node_modules.
        with open(os.path.join(root, "repo", "package-lock.json"), "w") as fh:
            fh.write("main\n")
        stub = os.path.join(root, "stub")
        os.makedirs(stub)
        with open(os.path.join(stub, "npm"), "w") as fh:
            fh.write("#!/bin/sh\ntouch npm-ran\n")
        os.chmod(os.path.join(stub, "npm"), 0o755)
        path = {"PATH": stub + os.pathsep + os.environ["PATH"]}
        for answer, gone in (("n", False), ("y", True)):
            d = tree(root, "deps-" + answer)
            with open(os.path.join(d, "package-lock.json"), "w") as fh:
                fh.write("branch\n")
            os.makedirs(os.path.join(d, "node_modules"))
            os.makedirs(os.path.join(d, ".next", "dev"))
            port_d = int(bash(root, 'feature_port "%s"' % d))
            server = subprocess.Popen(
                [sys.executable, "-m", "http.server", str(port_d), "--bind", "127.0.0.1"],
                cwd=d, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            try:
                for _ in range(40):
                    if bash(root, 'dev_pid %d' % port_d):
                        break
                    subprocess.run(["sleep", "0.1"])
                bash(root, 'ask() { printf -v "$2" %%s "%s"; }\n'
                           'is_yes() { [[ "$1" == y ]]; }\n'
                           'check_deps "%s"' % (answer, d), path)
                check("answer %s: server stopped" % answer, server.poll() is not None, gone)
                check("answer %s: .next/dev removed" % answer,
                      not os.path.isdir(os.path.join(d, ".next", "dev")), gone)
                check("answer %s: npm ran" % answer,
                      os.path.exists(os.path.join(d, "npm-ran")), gone)
            finally:
                if server.poll() is None:
                    server.kill()
                server.wait()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    print("%d/%d passed" % (total - len(failures), total))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
