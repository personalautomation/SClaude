#!/usr/bin/env python3
#
# A feature's servers listen on this machine alone.
#
# What is at stake: sclaude-proxy answers only this machine and the tailnet,
# and reaches a feature on 127.0.0.1. A dev server left to listen on every
# interface (`next dev` and `next start` do) is open to anybody on the same
# network past that filter. dev_loopback.cjs, loaded by dev_net_env into the
# commands that start them, moves such a listen to 127.0.0.1 and leaves an
# address the product names on purpose alone.
#
# Run it with: python3 tests/dev-loopback.py
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
SHIM = os.path.join(LIB, "tree", "dev_loopback.cjs")

failures = []
total = 0


def check(name, got, want):
    global total
    total += 1
    if got != want:
        failures.append((name, want, got))


# Each call listens the way its line says and prints the address it got.
FORMS = {
    "port alone": "s.listen(0, done)",
    "port and wildcard v4": "s.listen(0, '0.0.0.0', done)",
    "port and wildcard v6": "s.listen(0, '::', done)",
    "port and backlog": "s.listen(0, 511, done)",
    "port as a string": "s.listen('0', done)",
    "options without host": "s.listen({port: 0}, done)",
    "options with wildcard": "s.listen({port: 0, host: '::'}, done)",
    "options with port undefined": "s.listen({port: undefined}, done)",
    "options with both undefined": "s.listen({port: undefined, host: undefined}, done)",
    "callback alone": "s.listen(done)",
    "http server": None,
}
KEPT = {
    "an address named on purpose": ("s.listen(0, '::1', done)", "::1"),
}


def node_address(call, http=False, options=None):
    make = "require('http').createServer()" if http else "require('net').createServer()"
    code = ("const s = %s; const done = () => { console.log(s.address().address); s.close(); };"
            " %s;" % (make, call))
    env = dict(os.environ, NODE_OPTIONS=options or '--require="%s"' % SHIM)
    done = subprocess.run(["node", "-e", code], capture_output=True, text=True,
                          env=env, timeout=30)
    return done.stdout.strip() or done.stderr.strip()[-200:]


def bash(body, env=None):
    script = 'LIB="%s"\ninfo() { :; }\nwarn() { :; }\nsource "%s/tree/worktree.sh"\n%s\n' % (
        LIB, LIB, body)
    full = dict(os.environ)
    full.pop("NODE_OPTIONS", None)
    full.update(env or {})
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env=full, timeout=30).stdout.strip()


def main():
    if shutil.which("node"):
        for name, call in FORMS.items():
            got = node_address(call or "s.listen(0, done)", http=call is None)
            check("moved to loopback: " + name, got, "127.0.0.1")
        for name, (call, want) in KEPT.items():
            check("left alone: " + name, node_address(call), want)
        # A checkout under a path with a space: NODE_OPTIONS splits on it
        # unless the path is quoted, and every Node process would fail.
        spaced = tempfile.mkdtemp(prefix="dev loopback ")
        try:
            shutil.copy(SHIM, spaced)
            opt = bash('LIB="%s"; ( dev_net_env; echo "$NODE_OPTIONS" )' % spaced)
            check("a path with a space still loads", node_address("s.listen(0, done)", options=opt),
                  "127.0.0.1")
        finally:
            shutil.rmtree(spaced)
    else:
        print("node not found: the shim's own checks skipped")

    shim_opt = '--require="%s/tree/dev_loopback.cjs"' % LIB
    check("dev_net_env loads the shim",
          bash('( dev_net_env; echo "$NODE_OPTIONS" )'), shim_opt)
    check("dev_net_env keeps the product's NODE_OPTIONS",
          bash('( dev_net_env; echo "$NODE_OPTIONS" )',
               {"NODE_OPTIONS": "--max-old-space-size=4096"}),
          shim_opt + " --max-old-space-size=4096")

    # Both servers sclaude starts go through it: the dev server and the build
    # the regression serves. The suite's own parts do not (see dev_net_env).
    for path, starts in (("tree/worktree.sh", 'setsid --fork bash -c "$devcmd"'), ("ship/regression.sh", 'bash -c "$serve"')):
        text = open(os.path.join(LIB, path)).read()
        lines = text.splitlines()
        # The command and the line before it: a long start is continued with \.
        launch = [lines[i - 1] + lines[i] for i, line in enumerate(lines) if starts in line]
        check("%s: %s runs under dev_net_env" % (path, starts),
              bool(launch) and all("dev_net_env" in line for line in launch), True)
    # A session that has to start the server is sent to sclaude, not to npm.
    prompt = open(os.path.join(ROOT, "sclaude", "prompts", "_dev-server.md")).read()
    check("the session's prompt starts the server through sclaude",
          ("sclaude dev --no-browser" in prompt, "npm run dev" in prompt), (True, False))

    # A server that took every interface anyway is seen and said.
    if shutil.which("node") and shutil.which("ss"):
        server = subprocess.Popen(
            ["node", "-e", "const s=require('net').createServer().listen(0,'0.0.0.0',"
             "()=>console.log(s.address().port)); setTimeout(()=>{}, 20000)"],
            stdout=subprocess.PIPE, text=True, env={k: v for k, v in os.environ.items()
                                                    if k != "NODE_OPTIONS"})
        try:
            port = server.stdout.readline().strip()
            check("a port on every interface is seen",
                  bash('dev_exposed %s' % port), "0.0.0.0:%s" % port)
            wt = tempfile.mkdtemp()
            os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
            try:
                said = bash('warn() { echo "$*"; }; dev_exposed_warn %s %s' % (wt, port))
                check("started without the shim: a restart through sclaude is named",
                      ("past the proxy" in said, "sclaude dev --stop" in said), (True, True))
                with open(os.path.join(wt, ".sclaude/local/feature/state.json"), "w") as fh:
                    fh.write('{"feature": "some-feature"}')
                os.remove(os.path.join(wt, ".sclaude/local/feature/exposed-said"))
                said = bash('source "%s/core/state.sh"; warn() { echo "$*"; }; dev_exposed_warn %s %s'
                            % (LIB, wt, port))
                check("and names the feature, for a terminal in another tree",
                      "sclaude dev --stop some-feature && sclaude dev some-feature" in said, True)
            finally:
                shutil.rmtree(wt)
        finally:
            server.kill()
        # Started with dev_net_env, and open all the same: the shim was lost
        # on the way (the script set NODE_OPTIONS), so the product is to change.
        lost = subprocess.Popen(
            ["node", "-e", "const s=require('net').createServer().listen(0,'0.0.0.0',"
             "()=>console.log(s.address().port)); setTimeout(()=>{}, 20000)"],
            stdout=subprocess.PIPE, text=True,
            env=dict({k: v for k, v in os.environ.items() if k != "NODE_OPTIONS"},
                     SCLAUDE_DEV_LOOPBACK="1"))
        try:
            port = lost.stdout.readline().strip()
            wt = tempfile.mkdtemp()
            os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
            try:
                twice = 'warn() { echo "$*"; }; dev_exposed_warn %s %s; echo ---; dev_exposed_warn %s %s' % (
                    wt, port, wt, port)
                first, _, second = bash(twice).partition("---")
                check("the shim lost: the product's command is named",
                      ("past the proxy" in first, "NODE_OPTIONS" in first,
                       "sclaude dev --stop" in first), (True, True, False))
                check("said once per server process", second.strip(), "")
            finally:
                shutil.rmtree(wt)
        finally:
            lost.kill()
        loop = subprocess.Popen(
            ["node", "-e", "const s=require('net').createServer().listen(0,'127.0.0.1',"
             "()=>console.log(s.address().port)); setTimeout(()=>{}, 20000)"],
            stdout=subprocess.PIPE, text=True)
        try:
            port = loop.stdout.readline().strip()
            check("a port on loopback is not said", bash('dev_exposed %s' % port), "")
        finally:
            loop.kill()

    # A launcher sclaude started that gives the server an environment of its
    # own: the mark is on the parent, not the listener, and the product's
    # command is what to change, not a restart.
    if shutil.which("node") and shutil.which("ss"):
        launcher = subprocess.Popen(
            ["bash", "-c", "env -u SCLAUDE_DEV_LOOPBACK -u NODE_OPTIONS node -e \""
             "const s=require('net').createServer().listen(0,'0.0.0.0',"
             "()=>console.log(s.address().port)); setTimeout(()=>{}, 20000)\"; true"],
            stdout=subprocess.PIPE, text=True,
            env=dict(os.environ, SCLAUDE_DEV_LOOPBACK="1"))
        wt = tempfile.mkdtemp()
        os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
        try:
            port = launcher.stdout.readline().strip()
            said = bash('warn() { echo "$*"; }; dev_exposed_warn %s %s' % (wt, port))
            check("the mark on a parent: the product's command, not a restart",
                  ("environment" in said, "sclaude dev --stop" in said), (True, False))
        finally:
            subprocess.run(["pkill", "-P", str(launcher.pid)])
            launcher.kill()
            shutil.rmtree(wt)

    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    print("%d/%d passed" % (total - len(failures), total))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
