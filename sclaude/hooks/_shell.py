#!/usr/bin/env python3
#
# Command-line parsing shared by both hooks.
#
# Both look at a command the same way: split it on the separators, drop the
# wrappers, look at the first word. While this lived in two files, they could
# only diverge silently — and they would have diverged on the first edit to
# either of them.
import re
import shlex

# Command separators. `&` is a separator too: `git push &` puts the command in
# the background rather than cancelling it.
SEPARATORS = ("|", "||", "&&", ";", "&")

# The start of a heredoc: `<<EOF`, `<<'EOF'`, `<<"EOF"`, `<<-EOF`. The
# delimiter's name is what stands after the arrows; quotes around it do not
# affect the parsing.
HEREDOC = re.compile(r"<<-?\s*(?:'([^']*)'|\"([^\"]*)\"|([A-Za-z_][A-Za-z0-9_]*))")


def strip_heredocs(command):
    """Remove heredoc bodies, leaving the commands themselves.

    A heredoc's body is data, not a command: bash does not execute it but feeds
    it to the input. There is no reason to parse it as shell words, and it does
    harm: a single apostrophe in the text (`it's`, `don't`) looks like an
    opening quote, shlex raises ValueError, and the hook refuses the file write
    — not because it is forbidden but because it did not understand it. That is
    exactly what happened on a live feature: of the step's six heredocs exactly
    two were rejected, the two with an apostrophe in the body.

    The line with `<<EOF` stays: the redirection and the command's name are
    visible, and so is everything after the closing delimiter. A `gh pr merge`
    inside the body becomes text, which is what it is.
    """
    lines = command.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        # There can be several heredocs on one line: `cmd <<A <<B`. The bodies
        # follow one another in the order they were declared.
        delimiters = [m.group(1) or m.group(2) or m.group(3)
                      for m in HEREDOC.finditer(line)]
        i += 1
        for delimiter in delimiters:
            while i < len(lines) and lines[i].strip() != delimiter:
                i += 1
            i += 1  # the delimiter itself
    return "\n".join(out)


def split_separators(command):
    """Separate command separators with spaces.

    shlex.split cuts on spaces, while `;` and `|` are under no obligation to
    have one: in `sed -n 1p f.ts; git commit` the semicolon sticks to the file
    name, and the separator is simply not visible — the whole right-hand side of
    the chain escapes the parsing. `&&` separates itself, `;` and `|` do not.

    A newline is just as much a separator, and shlex.split swallowed it as a
    space: commands were glued into one, and `echo hi` with `git push origin
    main` on the next line looked like a call to `echo` with extra words. The
    steps' bans were bypassed with a newline, and a multi-line command is an
    everyday thing. We hand it over as `;`: the separator here means exactly the
    same.

    We leave quotes alone: `grep 'a;b' .` is not a chain.
    """
    out, quote, i = [], "", 0
    while i < len(command):
        ch = command[i]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "\n":
            out.append(" ; ")
            i += 1
            continue
        if ch in ";|&":
            # `&&` and `||` are one separator, not two: we cut them in
            # pairs.
            run = 2 if command[i:i + 2] in ("&&", "||") else 1
            out.append(" " + command[i:i + run] + " ")
            i += run
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def tokenize(command):
    """The command's words with the separators split off, or None.

    None means "parsing did not work out" — an unclosed quote. Such a string
    cannot be judged, and each hook decides for itself what to do about it: both
    choose to forbid, but their reasons differ.
    """
    try:
        return shlex.split(split_separators(strip_heredocs(command)))
    except ValueError:
        return None


# Wrappers with the real command standing behind them: `sudo git push`,
# `nohup npm …`. setsid is here too — not for the sake of permitting it but so
# that `setsid git push origin main` does not slip past.
#
# The list is shared by both hooks, and that is not a matter of taste. While
# each had its own, they diverged: no-code-in-planning.py knew five,
# forbidden-commands.py ten, and step 1 wrote files through `setsid rm`,
# `command rm`, `timeout 5 rm` and `nice npm install` — verified live, all four
# went through, whereas a bare `rm -rf` was rejected. _shell.py exists precisely
# because of that divergence.
WRAPPERS = ("sudo", "env", "time", "nohup", "xargs", "setsid", "command",
            "timeout", "stdbuf", "nice")

# Wrappers that swallow an argument of their own before the command's name.
#
# Removing the wrapper's name alone is not enough: `timeout 5 git push` leaves
# "5" as the first word, and `stdbuf -o0 git push` leaves "-o0", so comparing
# words[:2] with ["git","push"] misses. That is how `timeout 5 gh pr merge`,
# `stdbuf -o0 vercel --prod` and `xargs -n1 gh pr merge` went past the bans of
# steps 2-4 — that is a merge and a deploy to prod, the human's steps.
#
# A flag's value can stand both as a separate word (`-n 1`) and joined (`-n1`),
# so a separate word is swallowed only for known flags.
WRAPPER_VALUE_FLAGS = {
    "timeout": ("-k", "--kill-after", "-s", "--signal"),
    "xargs": ("-n", "--max-args", "-P", "--max-procs", "-I", "-d",
              "--delimiter", "-L", "-s", "--max-chars", "-E"),
    "stdbuf": ("-i", "--input", "-o", "--output", "-e", "--error"),
    "nice": ("-n", "--adjustment"),
    "env": ("-u", "--unset", "-C", "--chdir", "-S", "--split-string"),
}

# Wrappers whose first positional argument is not the command but a parameter
# of their own: `timeout 5 …` and `nice -n 5 …` take a number. For timeout it is
# the mandatory duration, and it is positional, without a flag.
WRAPPER_POSITIONAL = {"timeout": 1}


# git's own options, before the subcommand, that take their value as the next
# word; `--name=value` carries it in itself. Read past these, a check that
# looked at the second word as the subcommand saw `user.name=x` in
# `git -c user.name=x commit`, and let the commit through.
GIT_VALUED = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
              "--config-env", "--super-prefix"}


# Package runners: the real command stands behind them, exactly as behind a
# wrapper. They are deliberately NOT in WRAPPERS, and that is not tidiness.
# no-code-in-planning.py keeps `npx` in its own WRITERS list — at step 1 `npx` is
# banned as such, because it can run anything at all. Stripping it in the shared
# WRAPPERS would take that ban away: `npx tsc` would come out as `tsc` and step
# 1's hook would see a name it does not know. So the runners are stripped by a
# function of its own, and only forbidden-commands.py calls it.
RUNNERS = ("npx", "bunx", "pnpx")

# Runners spelled as a subcommand of their package manager.
RUNNER_PAIRS = (("pnpm", "dlx"), ("yarn", "dlx"))

# A runner's own flags that swallow the next word. `--package` names what to
# fetch, which is not yet the command being run.
RUNNER_VALUE_FLAGS = ("-p", "--package", "-c", "--call", "--registry")


def package_name(word):
    """A package specifier without its version: `vercel@59.17.0` → `vercel`.

    A fixing session wrote `npx --yes vercel@59.17.0 ls`, and without this the
    name never matches the ban table. A scoped package keeps its leading `@`:
    `@vercel/cli@1.2` → `@vercel/cli`.
    """
    if word.startswith("@"):
        rest = word[1:]
        return "@" + rest.split("@", 1)[0] if "@" in rest else word
    return word.split("@", 1)[0]


def skip_substitution(words, i):
    """The index past an assignment, following a command substitution to its end.

    `TOKEN=$(cat f)` arrives as two words and `A=`cat f`` likewise. We count the
    brackets — or the backticks — and stop where they close; an unbalanced one
    swallows the rest, which is the safe direction: nothing is then read as a
    command name.
    """
    depth = words[i].count("$(") - words[i].count(")")
    ticks = words[i].count("`") % 2
    i += 1
    while i < len(words) and (depth > 0 or ticks):
        depth += words[i].count("$(") - words[i].count(")")
        ticks = (ticks + words[i].count("`")) % 2
        i += 1
    return i


def strip_runners(words):
    """Drop a package runner, leaving the command it runs.

    `npx vercel --prod` is a deploy to prod however it is spelled, and until this
    existed it was not caught at all: the ban table compares the first word, and
    the first word was `npx`. Four fixing sessions on one feature found that by
    accident — one of them ran `npx vercel env ls` moments after a plain
    `vercel env ls` had been refused.
    """
    if len(words) > 1 and tuple(words[:2]) in RUNNER_PAIRS:
        words = words[2:]
    elif words and words[0] in RUNNERS:
        words = words[1:]
    else:
        return words

    i = 0
    while i < len(words) and words[i].startswith("-") and words[i] != "--":
        takes_value = words[i] in RUNNER_VALUE_FLAGS
        i += 1
        if takes_value and i < len(words):
            i += 1
    if i < len(words) and words[i] == "--":
        i += 1
    rest = words[i:]
    return [package_name(rest[0])] + rest[1:] if rest else rest


def strip_wrappers(words):
    """Drop the wrappers and their arguments, leaving the command itself.

    Returns a list of words with the path stripped (`/usr/bin/gh` → `gh`): the
    form with a path would otherwise slip past a comparison by name.

    Assignments of the form VAR=value before the command are dropped too —
    `FOO=1 rm` is a call to rm, not a separate command.

    An assignment whose value is a command substitution spans several words:
    shlex cuts `TOKEN=$(cat f)` into `TOKEN=$(cat` and `f)`, and the second has
    no `=` in it. Skipping only the first left `f)` as the command's name, and
    the whole ban table missed — `TOKEN=$(cat f) gh pr merge 82` and
    `VERCEL_TOKEN=$(cat ~/.config/vercel/cli-token) npx vercel --prod` both went
    through, verified live. That is a merge and a deploy to prod, the human's
    steps, and a fixing session found the shape by accident while reaching for a
    token. So the substitution is followed to its closing bracket.
    """
    i = 0
    while i < len(words):
        name = words[i].rsplit("/", 1)[-1]
        if "=" in words[i] and not words[i].startswith("-") \
                and "/" not in words[i].split("=")[0]:
            i = skip_substitution(words, i)
            continue
        if name not in WRAPPERS:
            break
        i += 1
        # The wrapper's own flags, and then its positional arguments.
        value_flags = WRAPPER_VALUE_FLAGS.get(name, ())
        while i < len(words) and words[i].startswith("-") and words[i] != "--":
            takes_value = words[i] in value_flags
            i += 1
            if takes_value and i < len(words):
                i += 1
        if i < len(words) and words[i] == "--":
            i += 1
        for _ in range(WRAPPER_POSITIONAL.get(name, 0)):
            if i < len(words) and not words[i].startswith("-"):
                i += 1
    return [w.rsplit("/", 1)[-1] for w in words[i:]]


# Grouping: `( … )` runs in a subshell, `{ …; }` in this one, and both run what
# is inside. shlex leaves the brackets on the words around them, so the first
# word was `(gh` and no ban matched. The brackets are taken off; a directory
# changed inside them is not followed out (follow_cd sees the brackets first
# and gives up), and from a group on the directory is unknown, so it never
# counts as scratch.
def ungroup(raw):
    """The words with grouping brackets removed, and whether there were any."""
    words, grouped, open_subs = [], False, 0
    for w in raw:
        if w in ("{", "}", "(", ")") and not open_subs:
            grouped = True
            continue
        while w.startswith("(") and not open_subs:
            w, grouped = w[1:], True
        # A `)` closes a `$(` opened earlier before it closes a group: shlex
        # cuts `TOKEN=$(cat f)` into `TOKEN=$(cat` and `f)`.
        open_subs += w.count("$(")
        closing = w.count(")") - w.count("(") + w.count("$(")
        while closing > 0 and open_subs:
            open_subs, closing = open_subs - 1, closing - 1
        if closing > 0 and w.endswith(")"):
            w, grouped = w.rstrip(")"), True
        if w:
            words.append(w)
    return words, grouped
