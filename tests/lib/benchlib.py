# What the benches share: sclaude's shell functions found by name.
#
# Many benches run a few of sclaude's shell functions on their own, cut out of
# the module that holds them. Each used to cut them out of a list of files it
# named, so a function moved from one module to another failed every bench
# that named the old one. Here a function is found by its name in the whole
# library (bin/sclaude and sclaude/lib/*/*.sh) — the names are unique there,
# and tests/paths.py fails the day two modules share one.
#
# Not a bench: tests/run runs tests/*.py, and this folder is not among them.
# A bench still names the modules it sources (`source "$LIB/core/state.sh"`),
# which is what `tests/run --changed` matches a change against.
#
#   sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
#   import benchlib
#   script = benchlib.functions(["session_watch_start", "session_watch_stop"])
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.path.join(ROOT, "sclaude", "lib")

# A function starts at `name() {` at the start of a line and ends at the first
# `}` at the start of a line outside a heredoc — a `}` in a heredoc's text is
# the text's — or is a whole function on its own line.
_START = re.compile(r"^([a-z_][a-z_0-9]*)\(\)\s*\{(.*)$")
# `<<word`, `<<-word`, `<<'word'`, never a here-string's `<<<`.
_HEREDOC = re.compile(r"(?<!<)<<-?(?!<)\s*(['\"]?)([A-Za-z_][A-Za-z_0-9]*)\1")
_index = None


def sources():
    """Every file the library's shell functions live in."""
    return [os.path.join(ROOT, "bin", "sclaude")] + sorted(glob.glob(os.path.join(LIB, "*", "*.sh")))


def definitions(text):
    """(name, text) for every function in a shell file's text."""
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = _START.match(lines[i])
        if not m:
            i += 1
            continue
        if m.group(2).strip().endswith("}"):
            yield m.group(1), lines[i] + "\n"
            i += 1
            continue
        body, waiting, j = [lines[i]], [], i + 1
        while j < len(lines):
            line = lines[j]
            body.append(line)
            if waiting:
                if line.strip() == waiting[0]:
                    waiting.pop(0)
            elif line == "}":
                break
            elif not line.lstrip().startswith("#"):
                # A comment that quotes `<<PY` opens no heredoc.
                waiting = [h[1] for h in _HEREDOC.findall(line)]
            j += 1
        yield m.group(1), "\n".join(body) + "\n"
        i = j + 1


def index():
    """{name: [(file, text)]} for every shell function in the library."""
    global _index
    if _index is None:
        found = {}
        for path in sources():
            with open(path, encoding="utf-8") as fh:
                for name, text in definitions(fh.read()):
                    found.setdefault(name, []).append((path, text))
        _index = found
    return _index


def duplicates():
    """Names defined in more than one place: a lookup by name would be a guess."""
    return sorted(n for n, defs in index().items() if len(defs) > 1)


def function(name):
    """The function's text, or None when the library has no such function."""
    defs = index().get(name)
    return defs[0][1] if defs else None


def where(name):
    defs = index().get(name)
    return defs[0][0] if defs else None


def functions(names, missing=None, script=None):
    """The named functions, one after another, ready to paste into a script.

    `script`: a file outside the library to cut them from instead — a script
    of its own such as bin/sclaude-watch, whose names nothing keeps unique.
    A name not found is passed to `missing(name)` — the bench's way of
    failing a check — and left out; without one, it raises."""
    found = None
    if script is not None:
        with open(script, encoding="utf-8") as fh:
            found = dict(definitions(fh.read()))
    out = []
    for name in names:
        text = function(name) if found is None else found.get(name)
        if text is None:
            if missing is None:
                raise KeyError("no shell function %s() in %s" % (name, script or "sclaude"))
            missing(name)
            continue
        out.append(text)
    return "\n".join(out)
