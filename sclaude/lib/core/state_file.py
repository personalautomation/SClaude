# A feature's state.json (and the other small JSON records sclaude keeps):
# changed under a lock, written whole.
#
# Several processes change the same state: the run itself, the session
# watcher, the local review, the friction review, the QA watcher. Each one
# reads the file, changes a field and writes it back. Without a lock two of
# them interleave and one's change is lost; written in place, a reader that
# comes in between finds the file empty or cut short, and state_get then
# reads "no such field" — which launches the wrong step.
#
#   import state_file
#   state_file.lock(path)           # before reading; held until the process exits
#   data = json.load(open(path))
#   ...
#   state_file.write(path, data)    # a temporary file beside it, renamed over it
#
# or, where the change is a block of its own:
#
#   with state_file.update(path) as data:
#       data["step"] = "code"
#
# The lock is a separate file, `<path>.lock`, so that renaming the record over
# itself never takes the lock away from a process waiting on it.
import contextlib
import fcntl
import json
import os
import tempfile

_held = {}


def lock(path):
    """Take the record's lock and keep it until the process ends (or unlock).

    A shell heredoc is one short process, so holding the lock to its end
    covers its read and its write without reshaping the code between them."""
    key = os.path.abspath(path)
    if key in _held:
        return
    fh = open(key + ".lock", "a")
    fcntl.flock(fh, fcntl.LOCK_EX)
    _held[key] = fh


def unlock(path):
    fh = _held.pop(os.path.abspath(path), None)
    if fh is not None:
        fh.close()


def write(path, data, **dump):
    """Write the record whole: readers see the old file or the new, never half."""
    dump.setdefault("indent", 2)
    dump.setdefault("ensure_ascii", False)
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", dir=folder)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, **dump)
            fh.write("\n")
        # mkstemp makes it private; the record it replaces was not.
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def update(path, create=False):
    """Read, change, write, under the lock. An exception inside — sys.exit
    included — leaves the record as it was."""
    lock(path)
    try:
        try:
            with open(path) as fh:
                data = json.load(fh)
        except FileNotFoundError:
            if not create:
                raise
            data = {}
        yield data
        write(path, data)
    finally:
        unlock(path)
