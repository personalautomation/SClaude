# The holding side's loop, shared by bin/keepawake-linux and bin/keepawake-macos
# — what KeepAwake.ps1 is on Windows.
#
# bin/keepawake decides; this executes. Every 30 seconds it reads the state file
# and asks state.should_hold — the same function whose word-for-word twin lives
# in KeepAwake.ps1 — and while the answer is yes it keeps the platform's lock:
# a systemd-inhibit lock on Linux, a power assertion on macOS. When the answer
# turns to no, or the state goes stale, the lock is dropped and the machine
# sleeps by its own rules again.
#
# The log lines are the Windows side's, word for word: "hold set", "hold
# released", "holding". `keepawake status` greps for exactly those, so they are
# coupled strings (see CLAUDE.md) — change them together or not at all.
#
# A platform's holder subclasses Holder with four things: acquire() takes the
# lock and says whether anything was granted, release() drops it, holding()
# says whether it is still held, and partial() names what was refused of it,
# once there is something to say. started() runs once the single-instance lock
# is this process's, before the first tick: whatever a dead holder left behind
# is cleared there, not before — a second holder that loses the lock must not
# touch what the running one holds.
import fcntl
import os
import signal
import sys
import time

from keepawake import state

POLL_SECONDS = 30
LOG_EVERY_SECONDS = 600
LOG_MAX_BYTES = 1024 * 1024


def log(message):
    path = state.hold_log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX_BYTES:
            with open(path, encoding="utf-8", errors="replace") as fh:
                tail = fh.readlines()[-200:]
            with open(path, "w", encoding="utf-8") as fh:
                fh.writelines(tail)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except OSError:
        pass


def until_label(data):
    until = data.get("until_ts") or 0
    return time.strftime("%H:%M", time.localtime(until)) if until else "?"


class Holder:
    """The lock and what has been said about it. tick() is one pass of the loop."""

    # What a refusal of every lock is logged as: "ERROR: <refused>".
    refused = "the lock was refused"

    def __init__(self):
        self.broken = False       # report a refusal once, not every 30 seconds
        self.logged_until = 0
        self.last_log = 0
        self.said_partial = False  # the "part refused" note, once per process

    def acquire(self):
        raise NotImplementedError

    def release(self):
        raise NotImplementedError

    def holding(self):
        raise NotImplementedError

    def partial(self):
        """The note on what of the lock was refused, or None when all was granted."""
        return None

    def held(self):
        """Whether a lock was taken and not released, alive or not."""
        raise NotImplementedError

    def started(self):
        """Called once this process holds the single-instance lock."""

    def tick(self, now=None):
        now = int(time.time()) if now is None else now
        data = state.read()
        want = state.should_hold(data, now)

        if want and not self.holding():
            # Either a fresh hold or a lock that died under us; both are a
            # "hold set", because from here on the machine is held again.
            if self.acquire():
                self.broken = False
                if data.get("hard_hold"):
                    log("hold set: a person is at the machine")
                else:
                    log("hold set, until %s" % until_label(data))
                note = self.partial()
                if note and not self.said_partial:
                    self.said_partial = True
                    log("NOTE: " + note)
                self.logged_until = data.get("until_ts") or 0
                self.last_log = now
            elif not self.broken:
                self.broken = True
                log("ERROR: " + self.refused)
        elif not want and self.held():
            self.release()
            log("hold released")
            self.logged_until = 0
            self.last_log = now
        elif want and (now - self.last_log) >= LOG_EVERY_SECONDS \
                and (data.get("until_ts") or 0) != self.logged_until:
            log("holding, until %s" % until_label(data))
            self.logged_until = data.get("until_ts") or 0
            self.last_log = now
        return want


def run(holder, name, lock_name):
    """The loop itself, one instance at a time: what the service or agent calls."""
    lock_file = os.path.join(state.linux_state_dir(), lock_name)
    os.makedirs(os.path.dirname(lock_file), exist_ok=True)
    lock = open(lock_file, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("exit: %s is already running (this one's pid is %d)" % (name, os.getpid()))
        return 0
    holder.started()

    def stop(signum, frame):
        if holder.held():
            holder.release()
            log("hold released")
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log("start: pid=%d, state=%s" % (os.getpid(), state.state_path()))
    while True:
        try:
            holder.tick()
        except Exception as error:  # the loop must outlive one bad read
            log("ERROR in the loop: %s" % error)
            holder.release()
        time.sleep(POLL_SECONDS)
