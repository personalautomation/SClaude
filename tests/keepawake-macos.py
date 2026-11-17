#!/usr/bin/env python3
#
# A bench for keepawake on macOS: where the state lives there, and
# bin/keepawake-macos, the holding side that replaces KeepAwake.ps1.
#
# The IOKit assertion is replaced by a fake that grants or refuses, and
# `sudo -n pmset` by a stub that records what it was asked and grants or
# refuses the sudoers rule, so every case runs on any machine. On a Mac the
# real assertion is made once too, and looked for where a person would look:
# `pmset -g assertions`.
#
# What each case would look like broken:
#
#   state path            the Mac's state goes where no holder reads it.
#   hold / release        the Mac sleeps under work, or never sleeps.
#   stale state           a dead counter keeps the Mac awake for ever.
#   the lid               with the rule, a closed lid sleeps under remote work;
#                         without it, pmset is run and refused every minute.
#   a killed holder       disablesleep stays on, and the Mac never sleeps again.
#   a second holder       one that loses the lock turns the running one's lid
#                         off, and a shut lid sleeps the Mac mid-work.
#   the person's own      a disablesleep the person set is turned off.
#   refusal               an assertion IOKit refused is taken for a hold.
#
# Run it with: python3 tests/keepawake-macos.py
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

failures = []


def check(name, got, want):
    if got == want:
        print("  PASS  %s" % name)
    else:
        failures.append(name)
        print("  FAIL  %s" % name)
        print("        want: %r" % (want,))
        print("        got:  %r" % (got,))


tmp = tempfile.mkdtemp()
os.environ.pop("KEEPAWAKE_STATE", None)
os.environ.pop("KEEPAWAKE_HOLD_LOG", None)
os.environ["KEEPAWAKE_PLATFORM"] = "macos"
os.environ["XDG_STATE_HOME"] = os.path.join(tmp, "xdg")

from keepawake import hold_loop, state  # noqa: E402

print("state on a Mac")
check("state-path-macos", state.state_path(),
      os.path.join(tmp, "xdg", "keepawake", "state.json"))
check("hold-log-macos", state.hold_log_path(),
      os.path.join(tmp, "xdg", "keepawake", "hold.log"))
check("platform-cli", subprocess.run(
    [sys.executable, os.path.join(ROOT, "keepawake", "state.py"), "platform"],
    capture_output=True, text=True, env=os.environ).stdout.strip(), "macos")
check("not-wsl", state.is_wsl(), False)
# With nothing forced, a Mac says so by itself.
os.environ.pop("KEEPAWAKE_PLATFORM")
if sys.platform == "darwin":
    check("platform-unforced", state.platform(), "macos")
os.environ["KEEPAWAKE_PLATFORM"] = "macos"

# --- the holder ---------------------------------------------------------------

calls = os.path.join(tmp, "pmset-calls")
stub = os.path.join(tmp, "pmset")
with open(stub, "w") as fh:
    # "check" is the sudoers question; anything else is a pmset run. RULE says
    # whether the rule is there.
    fh.write('#!/usr/bin/env bash\n'
             '[[ "$RULE" == yes ]] || exit 1\n'
             '[[ "$1" == check ]] && exit 0\n'
             '[[ -n "$PMSET_FAIL" ]] && exit 1\n'
             'echo "$*" >> %s\n' % calls)
os.chmod(stub, 0o755)
os.environ["KEEPAWAKE_PMSET"] = stub
os.environ["KEEPAWAKE_STATE"] = os.path.join(tmp, "state.json")
os.environ["KEEPAWAKE_HOLD_LOG"] = os.path.join(tmp, "hold.log")

loader = importlib.machinery.SourceFileLoader(
    "keepawake_macos", os.path.join(ROOT, "bin", "keepawake-macos"))
spec = importlib.util.spec_from_loader("keepawake_macos", loader)
km = importlib.util.module_from_spec(spec)
loader.exec_module(km)


class FakeAssertion:
    def __init__(self, grant=True):
        self.grant = grant
        self.live = set()
        self.next = 100

    def create(self):
        if not self.grant:
            return None
        self.next += 1
        self.live.add(self.next)
        return self.next

    def release(self, aid):
        self.live.discard(aid)


def set_state(**fields):
    data = state.blank()
    data.update(fields)
    state.write(data)


def log_lines():
    try:
        with open(os.environ["KEEPAWAKE_HOLD_LOG"]) as fh:
            return [line.split("  ", 1)[1].strip() for line in fh if "  " in line]
    except OSError:
        return []


def pmset_calls():
    try:
        with open(calls) as fh:
            return [line.strip() for line in fh]
    except OSError:
        return []


now = int(time.time())
os.environ["RULE"] = "no"
fake = FakeAssertion()
holder = km.Holder(fake)
try:
    print("hold and release, without the lid rule")
    set_state(updated_ts=now, until_ts=now + 3600)
    check("holds-while-wanted", holder.tick(now), True)
    check("assertion-made", len(fake.live), 1)
    check("hold-set-logged", log_lines()[-2].startswith("hold set, until "), True)
    check("idle-only-noted", log_lines()[-1].startswith("NOTE: only idle sleep is held"), True)
    check("pmset-not-run-without-the-rule", pmset_calls(), [])
    holder.tick(now)
    check("one-assertion-a-hold", len(fake.live), 1)

    set_state(updated_ts=now, until_ts=now - 1)
    holder.tick(now)
    check("released-when-not-wanted", (holder.holding(), fake.live), (False, set()))
    check("release-logged", log_lines()[-1], "hold released")

    print("hard hold and staleness")
    set_state(updated_ts=now, hard_hold=True)
    holder.tick(now)
    check("hard-hold-logged", log_lines()[-1], "hold set: a person is at the machine")
    check("idle-only-noted-once",
          sum(1 for line in log_lines() if line.startswith("NOTE: only idle")), 1)
    set_state(updated_ts=now - state.STALE_AFTER - 1, hard_hold=True)
    holder.tick(now)
    check("stale-releases", holder.holding(), False)

    print("the lid, with the rule")
    os.environ["RULE"] = "yes"
    holder = km.Holder(fake)
    set_state(updated_ts=now, until_ts=now + 3600)
    holder.tick(now)
    check("lid-held", (holder.lid, pmset_calls()), (True, ["-a disablesleep 1"]))
    check("lid-marked", os.path.exists(km.LID_MARK), True)
    check("no-note-with-the-lid", log_lines()[-1].startswith("hold set"), True)
    set_state(updated_ts=now, until_ts=now - 1)
    holder.tick(now)
    check("lid-let-go", pmset_calls()[-1], "-a disablesleep 0")
    check("mark-gone", os.path.exists(km.LID_MARK), False)

    print("a release pmset refused is tried again")
    set_state(updated_ts=now, until_ts=now + 3600)
    holder.tick(now)
    set_state(updated_ts=now, until_ts=now - 1)
    os.environ["PMSET_FAIL"] = "1"       # a passing refusal: the rule stands
    holder.tick(now)
    check("lid-kept-on-refusal", (holder.lid, holder.held()), (True, True))
    holder.tick(now)
    stuck = [line for line in log_lines() if line.startswith("holding: pmset refused")]
    check("refusal-said-once", (len(stuck), log_lines()[-1].startswith("holding:")), (1, True))
    # A hold that comes back meanwhile keeps the lid it still has, whatever
    # the sudoers question says now.
    set_state(updated_ts=now, until_ts=now + 3600)
    holder.tick(now)
    check("lid-kept-on-new-hold", holder.lid, True)
    # Refused once more as that hold ends: said again, not left at the hold's
    # "hold set" line.
    set_state(updated_ts=now, until_ts=now - 1)
    holder.tick(now)
    check("second-refusal-said", log_lines()[-1].startswith("holding: pmset refused"), True)
    set_state(updated_ts=now, until_ts=now - 1)
    os.environ.pop("PMSET_FAIL")
    holder.tick(now)
    check("lid-let-go-on-retry", (holder.lid, pmset_calls()[-1], log_lines()[-1]),
          (False, "-a disablesleep 0", "hold released"))

    print("a killed holder's lid")
    # A holder killed while holding leaves disablesleep on, and its mark.
    holder.tick(now)
    set_state(updated_ts=now, until_ts=now + 3600)
    holder.tick(now)
    check("held-again", pmset_calls()[-1], "-a disablesleep 1")
    # A second holder started while this one runs — by hand, or launchd
    # during a reload — finds the lock taken and exits: the running holder's
    # lid and mark are left as they are, or a shut lid sleeps it mid-work.
    lock = open(os.path.join(state.linux_state_dir(), ".macos-hold.lock"), "w")
    hold_loop.fcntl.flock(lock, hold_loop.fcntl.LOCK_EX | hold_loop.fcntl.LOCK_NB)
    before = len(pmset_calls())
    check("a-second-holder-exits", hold_loop.run(km.Holder(fake), "keepawake-macos",
                                                 ".macos-hold.lock"), 0)
    check("a-second-holder-leaves-the-lid", (len(pmset_calls()), os.path.exists(km.LID_MARK)),
          (before, True))
    lock.close()

    # The next holder, once the lock is its own, turns the left-over lid off.
    class Starting(km.Holder):
        def tick(self, now=None):
            raise SystemExit  # the first tick comes after started(); stop there
    try:
        hold_loop.run(Starting(fake), "keepawake-macos", ".macos-hold.lock")
    except SystemExit:
        pass
    check("the-next-holder-turns-it-off", pmset_calls()[-1], "-a disablesleep 0")
    # started() says it before run()'s "start:" line.
    check("and-says-it-let-go", log_lines()[-2:-1], ["hold released"])

    # One whose pmset refuses while the rule stands keeps the lid marked
    # held, for tick() to retry.
    open(km.LID_MARK, "w").close()
    os.environ["PMSET_FAIL"] = "1"
    refused_start = km.Holder(fake)
    refused_start.started()
    check("a-refused-start-keeps-the-lid", (refused_start.lid, refused_start.held()), (True, True))
    os.environ.pop("PMSET_FAIL")
    set_state(updated_ts=now, until_ts=now - 1)
    refused_start.tick(now)
    check("and-lets-it-go-on-the-next-tick", (refused_start.lid, os.path.exists(km.LID_MARK)),
          (False, False))
    check("a-lid-let-go-at-start-is-said", log_lines()[-1], "hold released")
    # With the rule gone the person took the lid back (LID_OFF turns it off
    # too): the mark goes, and nothing tries again or claims the lid.
    open(km.LID_MARK, "w").close()
    os.environ["RULE"] = "no"
    gone = km.Holder(fake)
    gone.started()
    check("rule-gone-at-start-lets-go", (gone.lid, os.path.exists(km.LID_MARK)), (False, False))
    gone.lid = True
    open(km.LID_MARK, "w").close()
    gone.release()
    check("rule-gone-at-release-lets-go", (gone.lid, os.path.exists(km.LID_MARK)), (False, False))
    # A sudo that cannot be asked at all (gone, or timing out) says nothing
    # about the rule: the lid stays held and marked, for the next try.
    gone.lid = True
    open(km.LID_MARK, "w").close()
    os.environ["KEEPAWAKE_PMSET"] = os.path.join(tmp, "no-such-pmset")
    gone.release()
    os.environ["KEEPAWAKE_PMSET"] = stub
    check("sudo-unasked-keeps-the-lid", (gone.lid, os.path.exists(km.LID_MARK)), (True, True))
    gone.lid = False
    os.unlink(km.LID_MARK)
    os.environ["RULE"] = "yes"
    set_state(updated_ts=now, until_ts=now + 3600)   # what the checks below hold under
    # The person's own disablesleep has no mark, and is left alone.
    before = len(pmset_calls())
    km.Holder(fake).started()
    check("the-persons-own-left-alone", len(pmset_calls()), before)

    print("refusal")
    refused = km.Holder(FakeAssertion(grant=False))
    refused.tick(now)
    refused.tick(now)
    check("refused-no-hold", refused.holding(), False)
    check("refusal-said-once",
          sum(1 for line in log_lines() if line.startswith("ERROR: IOKit refused")), 1)
finally:
    holder.release()

# --- the sudoers rule names what the holder runs ------------------------------

# sudo matches a rule's command word for word: a rule for `pmset -a
# disablesleep 1` does not let `pmset disablesleep 1` through, and the lid
# would quietly stay unheld.
print("the sudoers rule and the holder agree")
os.environ.pop("KEEPAWAKE_PMSET")
install = open(os.path.join(ROOT, "install.sh"), encoding="utf-8").read()
rule = install[install.index("lid_rule_text() {"):]
rule = rule[:rule.index("\n}\n")]
for value in ("1", "0"):
    argv = km.pmset_command(["-a", "disablesleep", value])
    check("holder-runs-sudo-n-%s" % value, argv[:2], ["sudo", "-n"])
    check("rule-names-disablesleep-%s" % value, " ".join(argv[2:]) in rule, True)
check("rule-asked-about-by-the-holder", "/usr/bin/pmset -a disablesleep 1" in rule
      and km.PMSET == "/usr/bin/pmset", True)

# --- the real assertion, on a Mac --------------------------------------------

if sys.platform == "darwin":
    print("a real assertion")
    real = km.Assertion()
    aid = real.create()
    check("iokit-grants", aid is not None, True)
    listed = subprocess.run(["pmset", "-g", "assertions"], capture_output=True,
                            text=True).stdout
    check("pmset-names-it", km.ASSERTION_NAME in listed, True)
    if aid is not None:
        real.release(aid)
    listed = subprocess.run(["pmset", "-g", "assertions"], capture_output=True,
                            text=True).stdout
    check("released-for-pmset", "pid %d(" % os.getpid() in listed
          and km.ASSERTION_NAME in listed, False)

if failures:
    print("\n%d failed: %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("\nall passed")
