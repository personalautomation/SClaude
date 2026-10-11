#!/usr/bin/env python3
#
# A step's session outlives the code that started it.
#
# bash keeps the functions it sourced, and a session runs for hours: the fix
# for step 4's rounds was pushed while #143's review session ran, and that
# session's /exit would have been handled by the old code — which closes the
# step with new findings open. code_reload, between claude's exit and anything
# done about it, replaces the process with the sclaude now on disk.
#
# Guarded here, with a stand-in for bin/sclaude:
#
#   * unchanged code carries on in the same process;
#   * a changed module hands the session's end to the new sclaude, with the
#     feature, the step and the session;
#   * SCLAUDE_NO_RELOAD keeps the old process;
#   * run_step calls it after claude, before session_ended, and the command it
#     names is dispatched to session_ended.
#
# Run it with: python3 tests/reload.py
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def functions(source, names):
    out = []
    for name in names:
        m = re.search(r"^%s\(\) \{\n.*?^\}\n" % re.escape(name), source, re.S | re.M)
        if not m:
            failures.append(("function-present-" + name, True, False))
            continue
        out.append(m.group(0))
    return "\n".join(out)


with open(os.path.join(LIB, "run.sh")) as fh:
    RUN = fh.read()
with open(os.path.join(ROOT, "bin", "sclaude")) as fh:
    BIN = fh.read()
BODY = functions(RUN, ["code_fingerprint", "code_reload"])

tmp = tempfile.mkdtemp()
try:
    inst = os.path.join(tmp, "inst")
    lib = os.path.join(inst, "sclaude", "lib")
    os.makedirs(lib)
    os.makedirs(os.path.join(inst, "bin"))
    with open(os.path.join(lib, "run.sh"), "w") as fh:
        fh.write("old() { :; }\n")
    with open(os.path.join(inst, "bin", "sclaude"), "w") as fh:
        fh.write('#!/usr/bin/env bash\necho "NEW SCLAUDE $*"\n')
    os.chmod(os.path.join(inst, "bin", "sclaude"), 0o755)

    def run(edit_between, env_extra=""):
        script = ('info() { echo "$*"; }\nINSTRUMENTS=%s; LIB=%s\n%s\n'
                  'SCLAUDE_CODE="$(code_fingerprint)"\n%s\n%s'
                  'code_reload demo review S1\necho "OLD CARRIES ON"\n'
                  % (inst, lib, BODY, edit_between, env_extra))
        return subprocess.run(["bash", "-c", script], capture_output=True,
                              text=True, timeout=30).stdout

    out = run("")
    check("unchanged-carries-on", "OLD CARRIES ON" in out and "NEW SCLAUDE" not in out, True)

    out = run('echo "new() { :; }" >> %s/run.sh' % lib)
    check("changed-hands-over", "NEW SCLAUDE _session-ended demo review S1" in out, True)
    check("changed-does-not-return", "OLD CARRIES ON" in out, False)

    out = run('echo "newer() { :; }" >> %s/run.sh' % lib, "SCLAUDE_NO_RELOAD=1\n")
    check("opt-out-carries-on", "OLD CARRIES ON" in out and "NEW SCLAUDE" not in out, True)

    # --- wiring -----------------------------------------------------------------
    tail = RUN[RUN.index("\nrun_step() {"):]
    tail = tail[:tail.index("\n}\n")]
    check("reload-before-session-ended",
          tail.rstrip().endswith('code_reload "$slug" "$step" "$session"\n'
                                 '  session_ended "$wt" "$slug" "$step" "$session"'), True)
    check("fingerprint-at-load", 'SCLAUDE_CODE="$(code_fingerprint)"' in BIN, True)
    check("dispatched", '_session-ended) shift; cmd_session_ended "$@" ;;' in BIN, True)
    cmd = BIN[BIN.index("cmd_session_ended() {"):]
    cmd = cmd[:cmd.index("\n}\n")]
    check("dispatch-ends-the-session", 'session_ended "$wt" "$slug" "$step" "$session"' in cmd, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
