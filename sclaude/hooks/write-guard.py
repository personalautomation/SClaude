#!/usr/bin/env python3
#
# Where a session may not write.
#
#   --team          a product's shared sclaude rules (.sclaude/team/) are
#                   written by its maintainers only. sclaude passes this for a
#                   session of somebody who is not on `maintainers` in the
#                   product's .sclaude/config.json (product_maintainer in
#                   developer.sh); their rules go to .sclaude/people/<name>/,
#                   and a maintainer can lift one into team/.
#   --readonly DIR  nothing under DIR, which may also be a file; given more
#                   than once, under none of them. sclaude passes its own
#                   live checkout for every session it runs: the others run
#                   from it, and a hook changed there changes all of them on
#                   their next call. A session changes sclaude in its tree's
#                   workshop instead (workshop.sh).
#   --allow DIR     the exception under a read-only DIR: sreview's state in
#                   the checkout's git directory, which reviewing a workshop's
#                   change writes.
#   --workshop DIR  the tree's workshop, read-only too until the session has
#                   opened it (`sclaude core-open`, which records the session
#                   in DIR.json; the record itself is never the session's to
#                   write).
#   --step          the session is a step's, which may not open the workshop:
#                   the refusal points it at the friction log instead.
#   --lenient       what cannot be told — a target in a variable, a directory
#                   that is not known — is refused only when the command names
#                   a read-only place at all. sclaude passes it for every
#                   session: they write into variables all day, and a review
#                   session runs the workshop's tests in loops. Without it
#                   anything unknown is refused.
#
# Reading is never refused. Like every hook here it guards against an
# accident, not against a session set on getting round it: a script written
# elsewhere and run is out of its sight. A program written in the line itself
# (`python3 - <<'EOF'`, `node -e`) is not: PROGRAM_WRITES.
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# First, so that a module failing to load, or anything raising later, refuses
# the call rather than letting it run (_failsafe.py). And that one failing to
# load refuses too, by hand: nothing else is there to.
try:
    import _failsafe  # noqa: E402
except Exception as _exc:  # noqa: BLE001
    print('{"hookSpecificOutput": {"hookEventName": "PreToolUse", '
          '"permissionDecision": "deny", "permissionDecisionReason": '
          '"sclaude\'s hook safety net (_failsafe.py) could not load, so this call is '
          'refused.  Tell the human and stop \u2014 the next move is theirs."}}')
    sys.exit(0)
_failsafe.install("write guard (write-guard.py)")
from _shell import (GIT_VALUED, KEYWORDS, QUOTED, closing_at, inner_command, scan,  # noqa: E402
                    strip_heads, strip_wrappers,
                    substitutions, tokenize, ungroup)

TEAM = re.compile(r"(^|/)\.sclaude/team(/|$)")
# Said of every path the session may not write. With a workshop the way to
# change sclaude is named: the workshop for the reviews, the friction log for
# a step, which may not open it (forbidden-commands.py CORE_OPEN_NO); without
# one (the epilogue, whose tree is gone) the change waits as a deferred entry.
READONLY_REASON = ("this session may not change {dir}: sclaude's live checkout is read-only "
                   "to every sclaude session, since the others run from it.")
WORKSHOP_REASON = (" Change sclaude in this tree's workshop, {workshop}, instead: "
                   "`sclaude core-open` opens it for this session.")
NO_WORKSHOP_REASON = (" Leave the change as a deferred entry of class sclaude-default.")
# Said of the workshop alone while this session has not opened it: the reason
# above named the live checkout, and a session refused a write into the
# workshop went looking for how its path led there.
CLOSED_REASON = ("this session may not change {workshop}: it is this tree's workshop, "
                 "a worktree of sclaude's checkout, and this session has not opened it.")
CORE_OPEN_REASON = (" `sclaude core-open` opens it for this session.")
STEP_REASON = (" Say in .sclaude/local/feature/friction.log what in sclaude got in your way "
               "and what the fix would be — the friction review after this session reads "
               "it — and carry on with the step's own work.")
# Said where the place a command writes cannot be told, rather than the reason
# above, which then named a place the command never meant: a loop's
# `>…/$(basename $t).out` into the scratchpad was told it may not change sclaude.
UNKNOWN_REASON = ("where this command writes cannot be told — a target in a variable or in "
                  "$( … ), or a directory that is not known — and it may be a place this "
                  "session may not change ({dir}). Write it with the path spelled out.")
REASON = ("the product's shared sclaude rules (.sclaude/team/) are written by its "
          "maintainers — `maintainers` in .sclaude/config.json. Put the rule in your own "
          ".sclaude/people/<name>/ instead; a maintainer can lift it into team/.")

# Bash words that change a file named after them.
WRITERS = ("cp", "mv", "rm", "tee", "touch", "install", "ln", "truncate", "mkdir",
           "rmdir", "dd")


# git subcommands that change a repository: in a read-only checkout they are
# writes, whichever file they name. remote, notes and reflog change it only in
# some of their forms; those are GIT_WRITE_FORMS.
GIT_WRITES = ("commit", "add", "rm", "mv", "reset", "checkout", "switch", "restore",
              "merge", "rebase", "cherry-pick", "revert", "stash", "apply", "am",
              "push", "tag", "branch", "pull", "clean", "worktree", "config",
              "fetch", "init", "submodule", "update-ref", "update-index", "symbolic-ref",
              "replace", "gc", "prune", "repack", "sparse-checkout", "filter-branch",
              "maintenance", "lfs", "bisect", "read-tree", "checkout-index", "clone")
GIT_WRITE_FORMS = {
    # `git -C <checkout> remote set-url origin x` repoints sclaude's own sync.
    "remote": ("add", "set-url", "remove", "rm", "rename", "prune", "set-head",
               "set-branches", "update"),
    "notes": ("add", "append", "copy", "edit", "merge", "prune", "remove"),
    "reflog": ("expire", "delete"),
}


# The forms of a GIT_WRITES subcommand that only read: "reading is never
# refused", and `git stash list` or `git config user.email` in sclaude's
# checkout were.
BRANCH_WRITES = ("-d", "-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy",
                 "-f", "--force", "-u", "--set-upstream-to", "--unset-upstream",
                 "--edit-description", "--track", "-t", "--no-track")
CONFIG_WRITES = ("--add", "--unset", "--unset-all", "--replace-all", "--rename-section",
                 "--remove-section", "-e", "--edit")
CONFIG_READS = ("--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l",
                "--get-color", "--get-colorbool", "get", "list")


# The flags of a fetch that only reads origin into the remote-tracking refs.
FETCH_READS = ("-q", "--quiet", "-v", "--verbose", "--prune", "-p", "--all", "--tags",
               "--no-tags", "--dry-run")

# Flags that put branch and tag in list mode, some with a value of their own.
# --sort, --format and --column are not among them: `git branch --sort=x new`
# creates new.
LIST_FLAGS = ("--contains", "--no-contains", "--merged", "--no-merged", "--points-at",
              "-v", "-vv", "-a", "-r", "--all", "--remotes", "-n")


def git_reads(sub, rest):
    """Whether this call of a GIT_WRITES subcommand only reads."""
    plain = [w for w in rest if not w.startswith("-")]
    flags = [w.split("=", 1)[0] for w in rest if w.startswith("-")]
    if sub == "stash":
        return plain[:1] in (["list"], ["show"])
    if sub == "worktree":
        return plain[:1] == ["list"]
    if sub == "fetch":
        # What origin has, into the remote-tracking refs, which sclaude's own
        # sync fetches all the time: nothing anybody runs changes with it. A
        # refspec into a branch of the checkout's (`main:main`, or one given
        # as --refmap's value) does, and --set-upstream writes its config: so
        # only these flags, and no refspec.
        return not any(":" in w for w in plain) and all(f in FETCH_READS for f in flags)
    if sub == "branch":
        if any(f in BRANCH_WRITES for f in flags):
            return False
        return not plain or any(f in ("-l", "--list", "--show-current") + LIST_FLAGS
                                for f in flags)
    if sub == "tag":
        if any(f in ("-d", "--delete", "-a", "-s", "-u", "-f", "--force", "-m", "-F") for f in flags):
            return False
        return not plain or any(f in ("-l", "--list", "-v", "--verify") + LIST_FLAGS
                                for f in flags)
    if sub == "config":
        if any(f in CONFIG_WRITES for f in flags) or plain[:1] in (["set"], ["unset"]):
            return False
        return any(f in CONFIG_READS for f in flags) or plain[:1] in (["get"], ["list"]) \
            or len(plain) == 1
    return False


# An interpreter that runs a program written in the line, from a heredoc or
# `-c`/`-e`, and what in that program writes a file. Its words name no target
# the way `cp` does, and `cd <workshop> && python3 - <<'EOF' … open(p, 'w')`
# rewrote a file there unseen. A program that runs in a read-only place and
# writes is refused: its paths are not read, so one relative to it may land
# there. One that only reads passes, as reading always does, and so does one
# that writes but runs elsewhere, whatever paths it reads or mentions.
INTERPRETER = re.compile(r"^(?:python[\d.]*|node|perl|ruby)$")
PROGRAM_WRITES = re.compile(
    r"\bopen\([^)]*['\"][rwax]*[wax+][bt]*['\"]"
    r"|\.write_(?:text|bytes)\(|\bos\.(?:remove|unlink|rename|replace|rmdir|truncate)\("
    r"|\bshutil\.(?:copy\w*|move|rmtree)\("
    r"|\.(?:writeFile|appendFile|rm|rmdir|rename|unlink|copyFile|truncate)(?:Sync)?\("
    r"|\bunlink\b|\bFile\.(?:write|delete|rename)\b")


def reads_program(words):
    """Whether an interpreter's call reads its program from a heredoc: an
    interpreter, then only flags or `-` before the `<<`. After a script's name
    the heredoc is the script's stdin, data rather than program."""
    if not words or not INTERPRETER.match(words[0].rsplit("/", 1)[-1]):
        return False
    for w in words[1:]:
        if re.match(r"\d*<<(?!<)", w):
            return True
        if not w.startswith("-"):
            return False
    return False


def heredoc_programs(command, cwd):
    """(body, directory) for each heredoc that holds an interpreter's program.

    A body belongs to the command on its own line that opens it: the calls of
    that line are the ones calls() finds through it and not before it, and
    the line's k-th body is its k-th `<<`. Matching each body on its own line
    keeps a misreading there, such as a heredoc in a substitution, from
    handing the body to a call on another line. The directory is the call's,
    followed through `cd` as calls() follows it.
    """
    spans = []
    if scan(command, 0, False, spans) is None:
        return []
    out, by_line = [], {}
    for start, stop, kind in sorted(spans):
        if kind == "doc":
            line = command.rfind("\n", 0, start - 1) + 1
            by_line.setdefault(line, []).append((start, stop))
    for line, bodies in by_line.items():
        end = bodies[0][0]
        before = calls(command[:line], cwd) or [] if line else []
        through = calls(command[:end], cwd)
        if through is None:
            continue
        opened = [(words, where) for words, where in through[len(before):]
                  for w in words if re.match(r"\d*<<(?!<)", w)]
        for (start, stop), (words, where) in zip(bodies, opened):
            if reads_program(words):
                out.append((command[start:stop], where))
    return out


def program_text(words):
    """The program an interpreter's call runs from its own words, or None:
    the value of -c or -e (`-c` stuck to its value too), or a here-string.
    Only before the first plain word: after a script's name the words are
    its arguments. A heredoc program is heredoc_programs()'."""
    for k, w in enumerate(words[1:], 1):
        if w.startswith("<<<"):
            return unmask(w[3:])
        if re.fullmatch(r"-[A-Za-z]*[ce]", w):
            return unmask(words[k + 1]) if k + 1 < len(words) else None
        if re.match(r"-[ce].", w):
            return unmask(w[2:])
        if not w.startswith("-"):
            return None
    return None


# Writers whose last argument alone is written: the rest is read. `-t DIR`
# (`--target-directory`) names the destination outright instead.
TO_LAST = ("cp", "mv", "install", "ln")
SEPS = ("|", "||", "&&", ";", "&")
# A redirection, alone or stuck to its neighbours: `>f`, `2>>f`, `hi>/x/f`.
REDIRECT = re.compile(r"(?:^|(?<=[^\\>]))\d?(?:>>?|&>>?)\|?(?!&)(.*)$")


def unwrap(segment):
    """The call itself, past `sudo`, `env X=1`, `timeout 5` and the like.

    strip_wrappers knows the wrappers but also cuts every word to its last
    path part, and a write's target needs its path; so only its count of words
    dropped from the front is taken. Without this `sudo git commit` and
    `env git commit` were not git calls at all here.
    """
    bare = strip_wrappers(segment)
    return segment[len(segment) - len(bare):] if bare else []


# perl switches whose value is the rest of the word: an `i` in `-Mstrict` or
# `-Ilib` is the module's or the path's, not in-place editing. `-0` and `-l`
# take digits only, and the cluster goes on after them.
PERL_VALUED = "MmIeExFdDC"


def perl_inplace(flag):
    """Whether a cluster of perl switches (`-pi`, `-0777pi.bak`) edits in place."""
    rest = flag[1:]
    k = 0
    while k < len(rest):
        ch = rest[k]
        if ch == "i":
            return True
        if ch in PERL_VALUED:
            return False
        k += 1
        if ch in "0l":
            while k < len(rest) and rest[k] in "0123456789abcdefABCDEFx":
                k += 1
    return False


def cd_to(where, args):
    """Where `cd args` from `where` lands, None when it cannot be told.

    Its options come first and are not the target: `cd -P DIR` and `cd --
    DIR` went to <cwd>/-P, and the read-only checkout they entered was never
    seen. `cd -` goes back to somewhere this does not know.
    """
    args = list(args)
    while args and args[0] in ("-P", "-L", "-e", "-@", "-Pe", "-LP", "-PL"):
        args = args[1:]
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        return moved(where, "~")
    if args[0] == "-" or len(args) > 1:
        return None
    return moved(where, args[0])


def moved(where, value):
    """The directory `cd value` from `where` lands in, None when it cannot be told."""
    value = os.path.expanduser(value)
    if not value or "$" in value or "`" in value:
        return None
    if os.path.isabs(value):
        return value
    return None if where is None else os.path.join(where, value)


def unmask(word):
    for ch, mask in QUOTED.items():
        word = word.replace(mask, ch)
    return word


def calls(command, cwd, seen=None):
    """(words, directory) for each command in the line, past its wrappers.

    None when the line cannot be parsed. The directory follows `cd`, inside a
    group too, and what a `( … )` or `{ …; }` changed is undone where it
    closes: a subshell's `cd` does not leave it, and a brace group's is not
    worth guessing past. One that cannot be told — a variable — is None, and
    stays None: a relative `cd` from an unknown place is still unknown.
    """
    # A `>` in quotes comes out masked, so that only a real redirection reads
    # as one (write_targets); unmask() gives a word back as it was written.
    words = tokenize(command, mask=True)
    if words is None:
        return None
    out, where, segment, saved, shape = [], cwd, [], [], {}
    for w in words + [";"]:
        if w not in SEPS:
            segment.append(w)
            continue
        segment = strip_heads(segment, shape)
        if not segment:
            continue
        opens = segment[0] in ("(", "{") or (segment[0].startswith("(") and not segment[0].startswith("$("))
        # What follows the bracket that closes a group is the outer shell's:
        # `(cd X; ls) > out` writes out where the line runs, not in X.
        k = closing_at(segment)
        tail = segment[k + 1:] if k is not None else []
        if k is not None:
            segment = segment[:k + 1]
        closes = k is not None
        if opens:
            saved.append((where, "{" if segment[0] == "{" else "("))
        flat, _ = ungroup(segment)
        while flat and flat[0] in KEYWORDS:
            flat = flat[1:]
        flat = unwrap(flat)
        segment = []
        name = flat[0].rsplit("/", 1)[-1] if flat else ""
        if flat:
            out.append((flat, where))
        # pushd and popd move too, to where cannot always be told: unknown.
        if name in ("pushd", "popd"):
            where = None
        if name == "cd":
            where = cd_to(where, [unmask(w) for w in flat[1:]])
        if closes:
            # A subshell's `cd` ends with it; a brace group runs in this shell
            # and its `cd` stays, which is not worth following: unknown.
            before, kind = saved.pop() if saved else (None, "{")
            where = before if kind == "(" else None
        if tail:
            out.append((tail, where))
        # Every directory the line is in, a line of bare assignments included:
        # `cd X && out=$(…)` has no call after the cd, and its substitution
        # runs in X.
        if seen is not None:
            seen.append(where)
    return out


def write_targets(command, cwd):
    """(word, directory it is relative to) for every path the command writes.

    None when the command cannot be parsed. Followed through `cd`, so
    `cd "$wt" && echo x > f` writes f in the worktree; a `cd` to a path with a
    variable in it makes the directory unknown, and an unknown directory is
    the sclaude checkout's to the read-only check, which is the safe side.
    """
    found = calls(command, cwd)
    if found is None:
        return None
    out = []
    for segment, where in found:
        # Redirections first, and out of the arguments: `cp a x > log` writes
        # x and log, and log was taken for cp's destination.
        args, skip = [], False
        for i, word in enumerate(segment):
            if skip:
                skip = False
                continue
            if word in (">", ">>", "&>", "&>>", "1>", "2>", "1>>", "2>>", ">|"):
                if i + 1 < len(segment):
                    out.append((segment[i + 1], where))
                skip = True
                continue
            m = REDIRECT.search(word)
            if m and m.group(1) and not m.group(1).startswith("&"):
                out.append((m.group(1), where))
                head = word[:m.start()]
                if head:
                    args.append(head)
                continue
            if m and not m.group(1) and i + 1 < len(segment):
                out.append((segment[i + 1], where))
                skip = True
                continue
            args.append(word)
        name = args[0].rsplit("/", 1)[-1] if args else ""
        rest = args[1:]
        if name == "mv":
            # mv removes what it moves: every path is written.
            out += [(w, where) for w in rest if not w.startswith("-")]
        elif name == "dd":
            out += [(w[3:], where) for w in rest if w.startswith("of=")]
        elif name in TO_LAST:
            target = next((rest[j + 1] for j, w in enumerate(rest[:-1])
                           if w in ("-t", "--target-directory")), None)
            target = target or next((w.split("=", 1)[1] for w in rest
                                     if w.startswith("--target-directory=")), None)
            plain = [w for w in rest if not w.startswith("-")]
            if target:
                out.append((target, where))
            elif plain:
                out.append((plain[-1], where))
        elif name in WRITERS:
            out += [(w, where) for w in rest if not w.startswith("-")]
        elif name in ("sed", "perl"):
            flags = [w for w in rest if w.startswith("-") and not w.startswith("--")]
            if name == "perl":
                inplace = any(perl_inplace(w) for w in flags)
            else:
                inplace = any("i" in w[1:].split(".", 1)[0] or w.startswith("-i") for w in flags) \
                    or "--in-place" in rest or any(w.startswith("--in-place=") for w in rest)
            if inplace:
                # The script is the first plain word unless -e or -f gave it.
                valued = ("-e", "-f", "-E") if name == "perl" else ("-e", "-f")
                plain, given, k = [], False, 0
                while k < len(rest):
                    w = rest[k]
                    if w in valued:
                        given, k = True, k + 2
                        continue
                    # The long spellings, the script stuck to them.
                    if w.startswith(("--expression=", "--file=")):
                        given, k = True, k + 1
                        continue
                    if not w.startswith("-"):
                        plain.append(w)
                    k += 1
                out += [(w, where) for w in (plain if given else plain[1:])]
        elif name == "git":
            # Past git's own options, to the subcommand; -C and --work-tree
            # move where the paths it names are, as for git_writes_in.
            k, here = 0, where
            while k < len(rest) and rest[k].startswith("-"):
                flag, has_value, value = rest[k].partition("=")
                if flag in GIT_VALUED and not has_value:
                    value = rest[k + 1] if k + 1 < len(rest) else ""
                    k += 1
                k += 1
                if flag in ("-C", "--work-tree"):
                    here = moved(here, unmask(value))
            sub = rest[k:k + 1]
            # checkout and restore write what they name; rm and mv change it in
            # the tree as their shell namesakes do.
            if sub in (["checkout"], ["restore"], ["rm"], ["mv"]):
                out += [(w, here) for w in rest[k + 1:] if not w.startswith("-")]
            # clone writes the directory it is given, the last word after the URL.
            elif sub == ["clone"]:
                plain = [w for w in rest[k + 1:] if not w.startswith("-")]
                if len(plain) > 1:
                    out.append((plain[-1], here))
    return [(unmask(w), where) for w, where in out]


def git_writes_in(command, cwd, inside, unknown=lambda: True):
    """Does a git call change a repository in a directory `inside` accepts?

    The directory is followed through `cd` and `git -C`; one that cannot be
    told (a variable) counts as inside, which is the safe side, unless
    `unknown` says otherwise (--lenient).
    """
    found = calls(command, cwd)
    if found is None:
        return False
    # GIT_DIR or GIT_WORK_TREE set in the line names the repository past the
    # directory, as --git-dir does: `GIT_DIR=$RO/.git git commit` committed
    # into the read-only checkout. The assignment is dropped with the
    # wrappers, so it is read off the line.
    named = []
    for word in tokenize(command) or []:
        m = re.match(r"^(?:export\s+)?GIT_(?:DIR|WORK_TREE)=(.*)$", word)
        if m:
            named.append(moved(cwd, m.group(1)))
    for call, where in found:
        if call[0].rsplit("/", 1)[-1] != "git":
            continue
        # Every place the call changes, not the last one named: -C moves like
        # `cd`, and --git-dir and --work-tree each name a part of the
        # repository outright, so `--git-dir=$RO/.git --work-tree=/tmp`
        # changes $RO, though the work tree is elsewhere.
        here, places, j = where, list(named), 1
        while j < len(call) and call[j].startswith("-"):
            name, has_value, value = call[j].partition("=")
            if name in GIT_VALUED and not has_value:
                value = call[j + 1] if j + 1 < len(call) else ""
                j += 1
            j += 1
            if name == "-C":
                here = moved(here, unmask(value))
            elif name in ("--git-dir", "--work-tree"):
                places.append(moved(here, unmask(value)))
        places.append(here)
        if j >= len(call):
            continue
        sub, rest = call[j], call[j + 1:]
        writes = (sub in GIT_WRITES and not git_reads(sub, rest)) or (
            sub in GIT_WRITE_FORMS
            and next((w for w in rest if not w.startswith("-")), "") in GIT_WRITE_FORMS[sub])
        if writes and any(inside(p) if p is not None else unknown() for p in places):
            return True
    return False


def refuses(payload, team, readonly, depth=0, allow=(), lenient=False, why=None):
    """The reason to refuse this call, or None."""
    tool = payload.get("tool_name")
    data = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()
    command = str(data.get("command", "")) if tool == "Bash" else ""

    def under(full, dirs):
        return any(full == d or full.startswith(d + os.sep) for d in dirs)

    def inside(path, base=None):
        full = os.path.realpath(os.path.join(base or cwd, os.path.expanduser(path)))
        return under(full, readonly) and not under(full, allow)

    reason = why or READONLY_REASON.format(dir=", ".join(readonly))
    vague = UNKNOWN_REASON.format(dir=", ".join(readonly))

    def named():
        """Whether the command names a read-only place, as written or as `~`."""
        home = os.path.expanduser("~")
        for d in readonly:
            forms = [d, d.replace(home, "~", 1), d.replace(home, "$HOME", 1)]
            rel = os.path.relpath(d, cwd)
            if not rel.startswith(".."):
                forms.append(rel)
            if any(f in command for f in forms):
                return True
        return False

    def unknown():
        """What cannot be told is refused, or with --lenient only near a guarded place."""
        return not lenient or named()

    def is_team(path):
        # As resolved: `.sclaude/people/../team/policy.json` is the team's.
        full = os.path.normpath(os.path.join(cwd, os.path.expanduser(path)))
        return team and TEAM.search(full) is not None

    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = str(data.get("file_path") or data.get("notebook_path") or "")
        if readonly and path and inside(path):
            return reason
        if is_team(path):
            return REASON
        return None
    if tool == "Bash":
        # What a substitution, a shell's -c string or eval runs writes as
        # surely as the line itself: `bash -c "echo x > $RO/f"` passed.
        # A substitution runs where the line has got to by then, which is not
        # told apart here: it is judged in every directory the line is in, and
        # an unknown one is the read-only checkout, the safe side.
        seen = []
        found = calls(command, cwd, seen) or []
        visited = []
        for there in [cwd] + seen:
            there = there if there is not None else (readonly[0] if readonly and unknown() else cwd)
            if there not in visited:
                visited.append(there)
        subs = substitutions(command)
        if subs is None:
            # A body left open is unparsable, as below: dropping it judged
            # nothing past it, and `$(cat <<EOF … It's … EOF); $(git commit)`
            # committed in the read-only checkout. Run from inside it, the
            # line need not name it.
            if readonly and (named() or inside(cwd)):
                return reason
            if team and TEAM.search(command):
                return REASON
        nested = [(text, there) for text in (subs or []) for there in visited]
        for words, where in found:
            inner = inner_command([words[0].rsplit("/", 1)[-1]] + [unmask(w) for w in words[1:]])
            if inner is not None:
                nested.append((inner, where if where is not None else
                               (readonly[0] if readonly and unknown() else cwd)))
        for text, where in nested:
            if depth >= 3:
                return "a command nested this deep cannot be judged"
            found_reason = refuses({"tool_name": "Bash", "tool_input": {"command": text},
                                    "cwd": where}, team, readonly, depth + 1, allow, lenient, why)
            if found_reason:
                return found_reason
        targets = write_targets(command, cwd)
        if targets is None:
            # Unparsable: refused only where it names a guarded place at all.
            if readonly and named():
                return reason
            if team and TEAM.search(command):
                return REASON
            return None
        if readonly:
            # A target with a variable in it: what the line set, then the
            # environment the shell will have. One still unknown, like
            # `"$f"` from a loop over sclaude's files, is taken as inside, the
            # safe side, as an unknown directory is: `RO=…; echo x > $RO/f`
            # was joined to the cwd as a literal and passed.
            assigned = dict(re.findall(r"(?:^|[;&|\s])([A-Za-z_]\w*)=([^\s;&|$`]+)", command))
            for i, (word, base) in enumerate(targets):
                if "$" in word or "`" in word:
                    known = re.sub(r"\$\{?([A-Za-z_]\w*)\}?",
                                   lambda m: assigned.get(m.group(1), m.group(0)), word)
                    known = os.path.expandvars(known)
                    if "$" in known or "`" in known:
                        if unknown():
                            return vague
                        continue
                    targets[i] = (known, base)
            for word, base in targets:
                if "$" in word or "`" in word:
                    continue
                # An unknown directory: an absolute path still tells, a relative
                # one is taken as the checkout's.
                if base is None and not os.path.isabs(os.path.expanduser(word)):
                    if unknown():
                        return vague
                    continue
                if inside(word, base):
                    return reason
            if git_writes_in(command, cwd, inside, unknown):
                return reason
            programs = [(program_text(words), where) for words, where in found
                        if INTERPRETER.match(words[0].rsplit("/", 1)[-1])]
            for text, where in programs + heredoc_programs(command, cwd):
                if text and PROGRAM_WRITES.search(text) and \
                        (not lenient if where is None else inside(where)):
                    return reason
        # The path as it resolves, from the directory the call runs in:
        # `cd .sclaude/team && echo x > policy.json` names no team path in a
        # word. Where the directory cannot be told, the word alone.
        if team and any(TEAM.search(word if base is None else
                                    os.path.normpath(os.path.join(base, os.path.expanduser(word))))
                        for word, base in targets):
            return REASON
    return None


def given(argv, name):
    return [os.path.realpath(argv[i + 1]) for i, a in enumerate(argv)
            if a == name and i + 1 < len(argv)]


def approved(record, session):
    """Whether the workshop's record lets this session write in it.

    The record holds the id sclaude launched the session with, which
    `sclaude core-open` took from SCLAUDE_SESSION. Claude Code may carry a
    running conversation on under a new id, and that is the one the hook is
    given; the process keeps its environment, which the hook inherits and the
    session cannot change. Either id names the session."""
    try:
        with open(record, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return False
    ids = (data or {}).get("approved") or []
    return any(sid and sid in ids for sid in (session, os.environ.get("SCLAUDE_SESSION")))


def main():
    argv = sys.argv[1:]
    team = "--team" in argv
    lenient = "--lenient" in argv
    readonly = given(argv, "--readonly")
    allow = given(argv, "--allow")
    workshop = (given(argv, "--workshop") or [""])[0]
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    why = None
    if readonly:
        why = READONLY_REASON.format(dir=", ".join(readonly)) + (
            STEP_REASON if "--step" in argv
            else WORKSHOP_REASON.format(workshop=workshop) if workshop else NO_WORKSHOP_REASON)
    closed = False
    if workshop:
        # The record says who may write in the workshop, and is never the
        # session's to write; the workshop is read-only until it says so.
        readonly.append(workshop + ".json")
        closed = not approved(workshop + ".json", payload.get("session_id"))
    data = payload.get("tool_input") or {}
    _failsafe.CONTEXT["subject"] = str(data.get("command") or data.get("file_path") or "")
    # A hook that raises exits non-zero, and Claude Code runs the call anyway.
    # Refused instead: an unreadable call near a guarded place is refused too.
    try:
        reason = refuses(payload, team, readonly, 0, allow, lenient, why)
        # The closed workshop is judged on its own, so that its refusal names
        # it rather than the live checkout.
        if not reason and closed:
            closed_why = CLOSED_REASON.format(workshop=workshop) + (
                STEP_REASON if "--step" in argv else CORE_OPEN_REASON)
            reason = refuses(payload, team, readonly + [workshop], 0, allow, lenient,
                             closed_why)
    except Exception as exc:  # noqa: BLE001
        reason = "the write guard failed on this call (%s: %s), so it is refused" % (
            type(exc).__name__, exc)
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
