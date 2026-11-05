#!/usr/bin/env python3
#
# Step 1 stays planning even after the plan is approved.
#
# Approving the plan lifts plan mode: that is how the confirmation dialogue
# works — "Yes" switches the session into a mode where Claude writes code. Step 1
# neither needs that nor benefits from it: development is carried out by step 2,
# in a separate session with a clean context, and what is written here will not
# reach it as intent anyway — only as unexpected changes in the worktree.
#
# So writing is rejected for the whole step, regardless of the mode.
#
# We leave ExitPlanMode alone: a deny in PreToolUse cancels the confirmation
# dialogue itself, and without it the human would never see the plan and there
# would be nothing to approve. (plan-on-disk.py denies it on purpose, for a
# plan with no acceptance criteria — that is its own decision, not this one.)
#
# Bash has to be parsed. It cannot be banned outright — step 1 reads the
# repository and the issues: git log, gh issue view, grep. Asking the model not
# to write through the terminal is not enough either: it has been verified that
# with Write blocked it calmly appends to a file through printf, not considering
# that a way around. So here is a list of what people write with, and everything
# else is let through.
import json
import os
import re
import shlex
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
_failsafe.install("planning guard (no-code-in-planning.py)")
from _friction import note
from _shell import HEREDOC, readable, strip_heredocs, strip_wrappers, substitutions, tokenize

REASON = (
    "Step 1 is planning, and writing is forbidden here even after the plan is "
    "approved: development is step 2, a separate session launched by the "
    "sclaude orchestrator. Through the terminal too — that is the same code, "
    "just a different tool. The session scratchpad is not banned: a "
    "redirection there passes when its path is written out, or set as a "
    "plain literal in a variable earlier in the same command, and so does "
    "mkdir or touch of a path written out there. The friction "
    "log is the exception: append to "
    ".sclaude/local/feature/friction.log what this refusal cost you. If the plan is ready "
    "and approved, tell the human and stop."
)

# The exception is named in the refusal itself. Without it the text reads as
# a ban on every file, and a live planning session took it at its word: it had
# a refusal worth reporting and did not even try the log, saying in its final
# report that writing files was forbidden at this step.

# Commands that change files. The command's name is checked rather than the
# whole string: "grep -r install ." must not fall under the ban because of a
# word inside it.
WRITERS = {
    "tee", "truncate", "dd", "install", "patch",
    "cp", "mv", "rm", "rmdir", "mkdir", "touch", "ln", "shred",
    "chmod", "chown", "perl", "python", "python3", "node",
    "npx", "make", "cargo", "go",
}

# These write only with a particular flag and read without it. sed without -i is
# the ordinary way of showing part of a file (`sed -n 1,130p`), and banning it
# took line-wise reading away from step 1: noticed in a live feature's friction
# log.
FLAG_WRITERS = {
    "sed": ("-i", "--in-place"),
}

# The mirror image of FLAG_WRITERS: these write by default and read with a
# particular flag. `node script.mjs` runs a file that may do anything, but
# `node -p` and `node -e` evaluate an expression and print it, and
# `node --version` prints a version. Banning the name outright made all three
# writes, and a live feature's planning session lost its Next version read to
# that: it needed the runtime value mid-reconnaissance and fell back to
# grepping package.json. The project's whole check:* suite is `node scripts/...`,
# so the ban met every step-1 session, not just that one.
#
# `npx` is the same: it runs a package that may do anything, but asking that
# package for its help or version only prints. A live feature's planning
# session lost `npx supabase db --help` to the ban on the name, twice, while
# working out how the migration history could be read. `-v` stays out: for
# many tools it means verbose, not version.
#
# `python -c` is the counterpart of `node -e`, and was left behind on the ban
# on the name: planning sessions lost a JSON read and an image header read to
# it, and fell back to grepping the file. A script (`python3 x.py`) still
# runs whatever it holds, so it stays a write. `-V` is safe here: for python
# it is the version, never verbose.
#
# A program fed in as a heredoc (`python3 - <<'EOF'`) is the same as `-c`:
# its code stands in the command, where the session and the human see it.
# Refusing it protected nothing: a live planning session had a read-only
# analysis refused that way and ran the very same code through `-c` a moment
# later, having only re-quoted it by hand. See program_in_command().
PYTHON_READ = ("-c", "-V", "--version", "-h", "--help")
READ_FLAGS = {
    "node": ("-p", "--print", "-e", "--eval", "-v", "--version", "-h", "--help"),
    "python": PYTHON_READ,
    "python3": PYTHON_READ,
    "npx": ("--help", "-h", "--version"),
}
# The ones that take a program on stdin; npx runs a package, not a program.
INTERPRETERS = ("node", "python", "python3")

# The git subcommands that change the working tree or the history. Reading git
# (log, diff, show, status) is needed by step 1 constantly.
GIT_WRITERS = {
    "add", "commit", "checkout", "switch", "restore", "reset", "revert",
    "merge", "rebase", "cherry-pick", "apply", "am", "push", "clean",
    "stash", "rm", "mv", "tag", "worktree", "config",
}

# Writing subcommands with reading actions of their own: `git worktree list`
# and `git stash list` only print. A live planning session lost
# `git worktree list` to the ban on the whole subcommand mid-reconnaissance and
# fell back to `git for-each-ref`. Only the action right after the subcommand
# counts: bare `git stash` pushes, and `git worktree add` creates a tree.
GIT_READ_ACTIONS = {
    "worktree": {"list"},
    "stash": {"list", "show"},
}

# Package managers install dependencies but also answer questions. Hence a
# separate list of subcommands — otherwise `npm ls` and `npm view` would count
# as writing.
PKG_WRITERS = {
    "install", "i", "add", "remove", "rm", "uninstall", "update", "up",
    "upgrade", "link", "prune", "dedupe", "publish", "run", "exec",
}

# For these commands writing depends on the subcommand: name → the list of
# writing ones.
SUBCOMMANDS = {
    "git": GIT_WRITERS,
    "npm": PKG_WRITERS,
    "pnpm": PKG_WRITERS,
    "yarn": PKG_WRITERS,
    # sclaude's own that change or send sclaude: the workshop is the
    # retrospective's and the reviews', and core-send is the person's word
    # (workshop.sh), which forbidden-commands.py refuses the other steps.
    "sclaude": {"core-open", "core-ready", "core-send"},
}


# The friction log is the only file step 1 may write: it is its way of saying
# that a restriction is getting in the way. Without the exception the channel
# would be closed exactly where it is needed most: writes() cuts every
# redirection, including one into the log itself.
LOG = ".sclaude/local/feature/friction.log"

# Redirection targets that write no file: the null device discards, and the
# standard streams go where the output was going anyway.
NULL_TARGETS = frozenset(("/dev/null", "/dev/stdout", "/dev/stderr"))

# Claude Code's own temp space. The system prompt tells every session to put
# its intermediate files in a scratchpad under this root, and a live planning
# session did exactly that: it saved the posted "User request" comment there to
# diff it against a corrected draft, and the redirection was refused as a
# write. The scratchpad is outside the worktree and per-session; step 2 never
# sees it, so nothing written there can become code.
SCRATCH = "/tmp/claude-{}".format(os.getuid())


def in_scratchpad(path):
    """Is the path strictly inside Claude Code's temp root?

    Normalised first, so `/tmp/claude-1000/../../home/x` does not pass; the
    separator is part of the prefix, so `/tmp/claude-1000x/f` does not either.
    """
    if not path:
        return False
    normalized = os.path.abspath(os.path.expanduser(path))
    return normalized.startswith(SCRATCH + os.sep)


def is_log(path):
    """Is this redirection target this tree's friction log, written out
    literally: relative to the tree, or under CLAUDE_PROJECT_DIR?"""
    return in_tree_as(path, LOG)


# Commands that only make a directory or an empty file, with the flags that
# change nothing about where. A live planning session needed a throwaway
# folder in its scratchpad to try a CLI against a config file, and `mkdir -p`
# there was refused although a redirection there passes; two earlier features
# lost a log entry to `mkdir -p` of the log's own folder chained before the
# append. Any other flag (`-m MODE`, `touch -r FILE`) keeps it a write: its
# value would read as a path here.
PATH_MAKERS = {
    "mkdir": ("-p", "--parents", "-v", "--verbose"),
    "touch": ("-c", "--no-create", "-a", "-m"),
}
LOG_DIR = ".sclaude/local/feature"


def in_tree_as(path, relative):
    """Is the path, written out literally, exactly `relative` in this tree?

    A suffix is not enough: `src/x/.sclaude/local/feature` ends the same way
    and makes folders in the product's source, and `../other/…` reaches
    another tree.
    """
    if not path or re.search(r"[$`*?\[{]", path) or ".." in path.split("/"):
        return False
    normal = os.path.normpath(os.path.expanduser(path))
    if normal == relative:
        return True
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    return bool(root) and normal == os.path.join(os.path.normpath(root), relative)


def makes_only_allowed(name, words):
    """Does this mkdir or touch reach only the scratchpad or the log's folder?

    The words are the ones as written, paths kept. Every operand must be a
    literal path: one with a variable, a substitution, a glob or a brace in
    it is expanded by bash after this check (`<scratch>/{a,../../etc}`
    normalises inside the scratchpad and expands outside it). A scratchpad
    path is absolute, so a `cd` earlier in the chain cannot move it; the
    log's folder, which mkdir alone may make, is relative to the tree.
    """
    flags = PATH_MAKERS[name]
    operands, skip = [], False
    for word in words:
        if skip:
            skip = False
            continue
        if re.match(r"\d*>|&>|<", word):
            skip = re.fullmatch(r"\d*>>?|&>>?|<<?<?", word) is not None
            continue
        if word.startswith("-"):
            if word not in flags:
                return False
            continue
        operands.append(word)
    if not operands:
        return False
    for word in operands:
        if re.search(r"[$`*?\[{]", word):
            return False
        if word.startswith(("/", "~")) and in_scratchpad(word):
            continue
        if name == "mkdir" and in_tree_as(word, LOG_DIR):
            continue
        return False
    return True


def allowed_path(path):
    """The files step 1 is supposed to write.

    Its own plan file is the first of them, and banning it cost a live session:
    plan mode allows the model exactly one file, ~/.claude/plans/<slug>.md, and
    that is where it puts the plan as the conversation goes. The hook rejected
    that write like any other, the plan stayed only as text in the conversation,
    and what went for approval was something the human could no longer re-read.

    The second is the friction log: it is the step's way of saying that a
    restriction is getting in the way, and closing it with that same restriction
    makes no sense.

    The third is the session scratchpad (see SCRATCH), so that the file tools
    agree with the shell about it.
    """
    if not path:
        return False
    normalized = os.path.abspath(os.path.expanduser(path))
    plans = os.path.abspath(os.path.expanduser("~/.claude/plans"))
    if normalized.startswith(plans + os.sep) or in_scratchpad(path):
        return True
    return normalized.endswith(os.path.join(".sclaude/local/feature", "friction.log"))


# A quoted span on the command line. The text of a log entry lives in one, or
# in a heredoc body, and what it says is not shell.
QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")


def substitutes(command, bare):
    """Would bash run something hidden inside the text of the entry?

    Taking the text out of the parsing is what lets an entry say anything, and
    it would let `$(rm -rf x)` say it too: bash expands a substitution inside
    double quotes and inside the body of a heredoc whose delimiter is bare. So
    those two places are searched, and single quotes and a quoted delimiter,
    where nothing expands, are not. A bare delimiter is judged by the whole
    command, body included: it is rarely what an entry is written with.
    """
    rest = bare
    for span in QUOTED.findall(bare):
        rest = rest.replace(span, "", 1)
        if span.startswith('"') and hides_write(span):
            return True
    if hides_write(rest):
        return True
    bare_delimiter = any(m.group(3) for m in HEREDOC.finditer(command))
    return bare_delimiter and hides_write(command)


# What bash takes literally inside double quotes and a bare heredoc body.
ESCAPED = re.compile(r"\\[\\`$]")

# A substitution with nothing nested in it.
SUBSTITUTION = re.compile(r"\$\(([^()`]*)\)|`([^`$]*)`")


def hides_write(text):
    """Does a substitution in the text run something that writes?

    Each simple one is parsed as a command of its own, so a timestamp from
    `$(date -Iseconds)` passes and `$(rm -rf x)` does not. Every substitution
    used to be refused, and a live planning session lost its entry to exactly
    that timestamp, and to an escaped backtick that bash prints as it is.
    Whatever is left that still looks like a substitution — one nested in
    another, or unbalanced — cannot be parsed here, and unknown is not
    permission.
    """
    text = ESCAPED.sub("", text)
    for match in SUBSTITUTION.finditer(text):
        body = match.group(1) if match.group(1) is not None else match.group(2)
        if writes(body):
            return True
    text = SUBSTITUTION.sub("", text)
    return "$(" in text or "`" in text


def only_writes_log(command):
    """Is the whole command a single append to the friction log?

    Checking the redirection targets alone is not enough: `echo x >>
    friction.log && rm -rf /tmp` also writes only to the log while doing
    something else entirely. So we require the command to be exactly one and its
    target to be the log.

    The text of the entry is left out of that check. A request is free-form and
    often several paragraphs, and one that mentioned `a; b`, a pipe or an arrow
    used to read as a chain or a second target, so the only file step 1 may
    write refused exactly the entries that describe a command.
    """
    if LOG not in command:
        return False
    bare = strip_heredocs(command).strip()
    if substitutes(command, bare):
        return False
    unquoted = QUOTED.sub("", bare)
    # Not a single separator: a chain is no longer "one entry in the log". A
    # newline outside the text separates commands just as `;` does.
    if any(sep in unquoted for sep in ("&&", "||", ";", "|", "\n")):
        return False
    try:
        shlex.split(bare)
    except ValueError:
        return False
    targets = re.findall(r">>?\s*(\S+)", unquoted)
    return len(targets) == 1 and targets[0].endswith("friction.log")


# Commands whose flag swallows the next argument. Without this `git -C path
# commit` parses as the subcommand "path": that is not in the list of writing
# ones, and the ban lets the commit through.
VALUE_FLAGS = {
    "git": {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"},
    "npm": {"-w", "--workspace", "--prefix", "-C"},
    "pnpm": {"-w", "--workspace", "--prefix", "-C", "--filter", "-F"},
    "yarn": {"--cwd"},
}


def reads_only(rest, flags):
    """Is there a flag among the arguments that makes this command read?

    A whole token is compared, or a short cluster's last letter: that is
    where python requires `-c` to stand (`python3 -Ic`), and it holds for
    every command here, so `node -xe` reads as `-e`. edits_in_place looks for
    a letter anywhere in a cluster, which is right for `-i` joining its
    neighbours (`sed -ne`); here a letter mid-cluster belongs to some other
    flag. The long form carries its argument
    through `=` (`--eval=1+1`), so we compare the part before it.

    After `--` there are no more flags: those are the script's own arguments.
    A reading flag after a script's name (`python3 x.py -c 1`) passes too:
    telling the script from a flag's value (`node --import x -e 1`,
    `python3 -W ignore -c 1`) would take each interpreter's value flags, and
    `-c` and `-e` may write anyway, so it would close nothing.
    """
    for arg in rest:
        if arg == "--":
            return False
        if not arg.startswith("-") or arg == "-":
            continue
        if arg.split("=", 1)[0] in flags:
            return True
        if not arg.startswith("--") and "-" + arg[-1] in flags:
            return True
    return False


def program_in_command(rest):
    """Does an interpreter read its program from a heredoc in the command?

    That is `python3 - <<'EOF'`, `node <<EOF` or `python3 - <<<'print(1)'`:
    the program is text standing in the command, like `-c`'s. Before `-`
    every argument must be a flag; a word that is not is a script's name, a
    flag's value (`-W ignore`, left a write rather than learn every
    interpreter's value flags) or a file fed to stdin (`- < x.py`), and in
    each the program is not in sight. After `-` the words are the program's
    own arguments (`python3 - data.json <<'EOF'`). An output redirection is
    skipped here with its target: writes() has judged it already. The words
    are the ones as written, paths kept: strip_wrappers() leaves `null` of
    `2>/dev/null`.
    """
    heredoc, skip, dash = False, False, False
    for arg in rest:
        if skip:
            skip = False
            continue
        if arg.startswith("<<"):
            heredoc = True
            # A delimiter or a here-string standing as a word of its own.
            skip = arg in ("<<", "<<-", "<<<")
            continue
        if re.match(r"\d*>|&>", arg):
            skip = re.fullmatch(r"\d*>>?|&>>?", arg) is not None
            continue
        if arg == "-":
            dash = True
            continue
        if arg.startswith("-") or dash:
            continue
        return False
    return heredoc


def substitution_writes(command):
    """Does a substitution in the command run something that writes?

    `$(( … ))` is arithmetic, not a command: its `>` compares, and only the
    substitutions inside it run. None from substitutions() is a write.
    """
    inner = substitutions(command)
    if inner is None:
        return True
    for part in inner:
        if part.startswith("(") and part.endswith(")"):
            if substitution_writes(part[1:-1]):
                return True
        elif writes(part):
            return True
    return False


def edits_in_place(rest, flags):
    """Is there a flag among the arguments for editing a file in place?

    A short flag joins up with its neighbours and with its own argument:
    `-i.bak`, `-ie`, `-n -i`. So for single-character ones we look for the letter
    in the cluster rather than comparing the whole token. The long form carries
    its argument through `=` (`--in-place=.bak`), so we compare the part before
    it.

    After `--` there are no more flags — those are file names, and an `-i` among
    them means a file with that name.
    """
    for arg in rest:
        if arg == "--":
            return False
        if not arg.startswith("-") or arg == "-":
            continue
        if arg.startswith("--"):
            if arg.split("=", 1)[0] in flags:
                return True
            continue
        cluster = arg[1:].split("=", 1)[0]
        if any(f[1:] in cluster for f in flags if len(f) == 2):
            return True
    return False


# A redirection target that starts with a variable: `$F`, `${F}`, `$D/x.md`.
VARIABLE_TARGET = re.compile(r"\$(?:([A-Za-z_][A-Za-z0-9_]*)|\{([A-Za-z_][A-Za-z0-9_]*)\})")
# Builtins that set a variable named as a bare word: `read F`, `printf -v F`.
RESETTERS = frozenset(("export", "declare", "local", "readonly", "typeset",
                       "read", "readarray", "mapfile", "printf", "unset", "let"))
ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", re.S)
# A double-quoted word that is only such a target, `"$F"`: the redirection scan
# keeps its text, where it drops every other quoted span.
QUOTED_VARIABLE = re.compile("\"(\\$\\{?[A-Za-z_][A-Za-z0-9_]*\\}?[^\"'$`\\\\\\s]*)\"")


def assigned_target(target, tokens):
    """The literal path a redirection target starting with `$NAME` is sure to
    be, or None.

    A live planning session named its scratchpad file once, `F=<path> && cat >
    $F <<'EOF' … && gh api … -F body=@$F`, and was refused: `$F` is not a
    path, and a target that cannot be read is a write. Here it can be read,
    because the command itself gives it a literal value before the
    redirection, and nothing can run between the two.

    So, strictly: NAME is assigned exactly once in the whole command, as a
    command of its own (`F=x cat > $F` is a prefix, and bash expands the
    redirection before that assignment applies), at the start of a chain of
    `&&` that reaches the redirection (a `;` only right after the assignment).
    Any `||`, `|` or `;` elsewhere before the redirection would let it run
    with the assignment skipped or in a subshell, and `$F` would then be
    whatever the environment holds. Between the two, nothing sets NAME
    again: `export F=…`, `read F`, `printf -v F`, `F+=…` (RESETTERS); a bare
    word that only happens to be the name (`--json` for `json=…`) is not that. The value, and
    whatever follows the variable in the target, hold no `$` or backtick: a
    substitution is not a literal. Anything else is None, and stays a write.
    """
    match = VARIABLE_TARGET.match(target)
    if not match or tokens is None:
        return None
    name = match.group(1) or match.group(2)
    tail = target[match.end():]
    if "$" in tail or "`" in tail:
        return None
    # Line breaks after `&&` continue the chain; tokenize() reads each as `;`.
    kept = []
    for token in tokens:
        if not (token == ";" and kept and kept[-1] == "&&"):
            kept.append(token)
    tokens = kept
    redirect = None
    for i, token in enumerate(tokens):
        if token.endswith(">" + target) or (
                token == target and i and tokens[i - 1] in (">", ">>", "&>", "&>>")):
            redirect = i
            break
    if redirect is None:
        return None
    separators = ("|", "||", "&&", ";", "&")
    assignments = [i for i, t in enumerate(tokens)
                   if t.startswith(name + "=")
                   and (i == 0 or tokens[i - 1] in separators)]
    if len(assignments) != 1 or assignments[0] > redirect:
        return None
    at = assignments[0]
    after = tokens[at + 1] if at + 1 < len(tokens) else None
    if after not in ("&&", ";"):
        return None
    for i, token in enumerate(tokens[:redirect]):
        if token in separators and token != "&&" and i != at + 1:
            return None
    head = None
    for token in tokens[at + 1:redirect]:
        if token in separators:
            head = None
            continue
        if head is None and not ASSIGNMENT.fullmatch(token):
            # `IFS= read -r F`: a prefix assignment is not the command.
            head = token
        if re.match(re.escape(name) + r"(\+?=|\[)", token) or (
                token == name and head in RESETTERS):
            return None
    value = ASSIGNMENT.fullmatch(tokens[at]).group(2)
    if not value or "$" in value or "`" in value:
        return None
    return value + tail


def writes(command):
    """Does it look as though the command changes files."""
    if only_writes_log(command):
        return False
    # What a substitution runs is a command of its own, judged as one. Nothing
    # here looked inside them, and `echo $(rm -rf x)`, `x=$(rm x)` and a bare
    # heredoc body holding `$(rm x)` all passed: the words around the
    # substitution read. A line whose substitutions cannot be told (a bracket
    # or a heredoc left open) cannot be judged, so it writes.
    if substitution_writes(command):
        return True
    # Redirecting output to a file: > file, >> file. It does not count inside
    # quotes, so we look at the string without them.
    #
    # Nor inside a heredoc: the body is data fed to stdin, not shell. The scan
    # used to run over the raw command, and the "User request" comment that
    # plan.md asks step 1 to post was refused as a write — its marker
    # `<!-- sclaude:user-request -->` ends in `-->`, which parsed as a
    # redirection into `##`, the heading on the next line. tokenize() below
    # already stripped heredocs; this scan runs before it and did not. It
    # reads the line tokenize() reads: in the raw one an apostrophe in
    # `"$(echo "it's")"` paired with a later one and hid the `>` between them.
    line = QUOTED_VARIABLE.sub(r"\1", readable(command) or strip_heredocs(command))
    unquoted = re.sub(r"'[^']*'|\"[^\"]*\"", "", line)
    for match in re.finditer(r"(?<![0-9<>])>>?(?!&)\s*([^\s;|&<>()]*)", unquoted):
        # The target decides. The bare `>` used to be enough, and it made
        # `cmd >/dev/null 2>&1` a write — the ordinary way to silence a probe,
        # which creates no file. `2>/dev/null` escaped only because the digit
        # falls under the lookbehind: an accident of the parsing, not a
        # decision about the device.
        #
        # The target stops at the shell's own punctuation. Taking \S* instead
        # swallowed the separator — `>/dev/null; cat f` parsed its target as
        # "/dev/null;" and stayed a write, which is the very form the log
        # entries were written in.
        #
        # A target we cannot read is still a write: unknown is not permission,
        # and an empty capture (`>` with nothing after it) is unknown.
        #
        # The scratchpad writes nothing that step 2 will see. Only the
        # redirection is let through: the rest of the chain is still parsed
        # below.
        #
        # A variable set to a literal earlier in the same command is read as
        # that literal (assigned_target()).
        #
        # The friction log passes here too, so an append to it may stand in a
        # chain: the other links are still judged below. only_writes_log()
        # alone required the append to be the whole command, and a live
        # planning session lost an entry chained with its next reads to that.
        target = match.group(1)
        target = assigned_target(target, tokenize(command)) or target
        if target not in NULL_TARGETS and not in_scratchpad(target) and not is_log(target):
            return True

    tokens = tokenize(command)
    if tokens is None:
        # An unclosed quote — it cannot be parsed, and it certainly cannot be
        # let through blindly.
        return True

    # We cut the chain on the separators and strip the wrappers together with
    # their arguments from every link. The list of wrappers here used to be
    # shorter than the one in steps 2-4's hook, and step 1 wrote files around the
    # ban on that: `setsid rm`, `command rm`, `timeout 5 rm`, `nice npm install`
    # — verified, all four went through, whereas a bare `rm -rf` was rejected.
    # The parsing is now shared.
    chains, current = [], []
    # A sclaude core command is refused for a reason of its own (SCLAUDE_REASON),
    # but only when nothing else in the chain writes: the rest is still read.
    core = False
    for token in tokens:
        if token in ("|", "||", "&&", ";", "&"):
            if current:
                chains.append(current)
            current = []
            continue
        current.append(token)
    if current:
        chains.append(current)

    for raw in chains:
        words = strip_wrappers(raw)
        if not words:
            continue
        name = words[0]
        rest = words[1:]
        if name in READ_FLAGS and reads_only(rest, READ_FLAGS[name]):
            # Reading closes this command, not the chain: `node -p 1 && rm -rf
            # x` still writes. The same reasoning as for FLAG_WRITERS below.
            continue
        if name in INTERPRETERS and program_in_command(raw[len(raw) - len(rest):]):
            # Likewise this command alone.
            continue
        # Not behind xargs: the words it reads from stdin become operands
        # this check never saw (`… | xargs mkdir -p <scratch>/x`).
        behind_xargs = "xargs" in (w.rsplit("/", 1)[-1] for w in raw[:len(raw) - len(rest)])
        if name in PATH_MAKERS and not behind_xargs \
                and makes_only_allowed(name, raw[len(raw) - len(rest):]):
            # This command alone, like the reading flags above.
            continue
        if name in WRITERS:
            return True
        if name in FLAG_WRITERS:
            if edits_in_place(rest, FLAG_WRITERS[name]):
                return True
            # Without the editing flag this is reading — but only this command.
            # Anything at all may stand further down the chain, and breaking off
            # the parsing here means opening writing to anyone who starts the
            # line with `sed -n 1p file &&`.
            continue
        if name in SUBCOMMANDS:
            # The first word without a dash is the subcommand; everything
            # before it is the command's own flags, and some of them carry the
            # next argument with them (`git -C path commit`). A bare name with no
            # subcommand writes nothing: `git` prints its help.
            skip = False
            for i, arg in enumerate(rest):
                if skip:
                    skip = False
                    continue
                if arg.startswith("-"):
                    skip = arg in VALUE_FLAGS.get(name, ())
                    continue
                if arg in SUBCOMMANDS[name]:
                    if name == "sclaude":
                        core = True
                        break
                    actions = GIT_READ_ACTIONS.get(arg) if name == "git" else None
                    # The very next word, not the next non-flag: in
                    # `git stash -m list` the "list" is a message, and that
                    # stash pushes.
                    action = rest[i + 1] if i + 1 < len(rest) else None
                    if actions and action in actions:
                        break
                    return True
                break
            # A reading subcommand closes only this command, not the chain:
            # `git log && git commit` writes, however much reading stands before
            # it.
            continue
    # Truthy for every caller; "sclaude" tells deny() which reason it is.
    return "sclaude" if core else False


# Its own reason for sclaude's commands in SUBCOMMANDS, when nothing else in
# the command writes (writes() returns "sclaude"): they write no file,
# and the generic one would read to the friction review as a false refusal
# to loosen. The words are forbidden-commands.py's CORE_OPEN_NO and
# CORE_SEND_NO, said for step 1; its ending is one of collect-denials.py's
# OWN_MARKERS, since this hook writes the log itself.
SCLAUDE_REASON = (
    "Step 1 does not change or send sclaude itself: its workshop is the "
    "retrospective's and the reviews', and `sclaude core-send` is the person's "
    "word. If something in sclaude got in your way, append it to "
    ".sclaude/local/feature/friction.log. Then carry on with the step's own work.")


def deny(subject="", reason=REASON):
    # Into the log, so that the review between steps sees what the step tripped
    # over.
    note("plan", "hook", subject, reason)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))
    sys.exit(0)


try:
    payload = json.load(sys.stdin)
except ValueError:
    # Parsing the input did not work out: we pass rather than ban at random.
    sys.exit(0)

tool = payload.get("tool_name", "")
tool_input = payload.get("tool_input") or {}
_failsafe.CONTEXT["subject"] = str(tool_input.get("command") or tool_input.get("file_path") or tool)

if tool in ("Write", "Edit", "NotebookEdit"):
    if not allowed_path(str(tool_input.get("file_path", ""))):
        deny(tool)
elif tool == "Bash":
    found = writes(str(tool_input.get("command", "")))
    if found:
        deny(str(tool_input.get("command", "")), SCLAUDE_REASON if found == "sclaude" else REASON)

sys.exit(0)
