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
        # `2>&1` and `&>f` are redirections, not a background `&`.
        if ch == "&" and (command[i - 1:i] in (">", "<") or command[i + 1:i + 2] == ">"):
            out.append(ch)
            i += 1
            continue
        # `>|` is a redirection that overwrites, not a pipe.
        if ch == "|" and command[i - 1:i] == ">":
            out.append(ch)
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


# What a `>` inside quotes becomes with tokenize(…, mask=True): not a
# redirection, which is all a hook looking for redirections needs to know.
# Brackets too: `echo "a)"` closes no group.
QUOTED_GT = "\x01"
QUOTED_OPEN = "\x02"
QUOTED_CLOSE = "\x03"
QUOTED = {">": QUOTED_GT, "(": QUOTED_OPEN, ")": QUOTED_CLOSE}


def mask_quoted(command):
    """The command with every `>`, `(` and `)` inside quotes masked (QUOTED).

    The words come out of shlex with their quotes gone, so `git commit -m
    "a -> b"` looked like a redirection to a file called ` b`.
    """
    out, quote, i = [], "", 0
    while i < len(command):
        ch = command[i]
        if ch == "\\" and quote != "'" and i + 1 < len(command):
            out.append(command[i:i + 2])
            i += 2
            continue
        if quote:
            if ch == quote:
                quote = ""
            out.append(QUOTED.get(ch, ch))
        else:
            if ch in "'\"":
                quote = ch
            out.append(ch)
        i += 1
    return "".join(out)


def tokenize(command, mask=False):
    """The command's words with the separators split off, or None.

    None means "parsing did not work out" — an unclosed quote. Such a string
    cannot be judged, and each hook decides for itself what to do about it: both
    choose to forbid, but their reasons differ. With `mask`, a `>` in quotes
    comes out as QUOTED_GT.
    """
    try:
        command = strip_heredocs(command)
        return shlex.split(split_separators(mask_quoted(command) if mask else command))
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
            "timeout", "stdbuf", "nice", "exec")

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
    "exec": ("-a",),
}

# Words that open a command inside `if`, a loop or a negation: the command
# after them is the one that runs. `if true; then gh pr merge 5; fi` put
# `then` first, and the ban table compares the first word.
KEYWORDS = ("if", "then", "else", "elif", "while", "until", "do", "!")


def strip_keywords(words):
    while words and words[0] in KEYWORDS:
        words = words[1:]
    return words


def substitutions(command):
    """The commands inside $( … ), <( … ), >( … ) and backticks, or None.

    Each runs as a command of its own, and `x=$(gh pr merge 5)` merged with no
    ban looking: the words around it are an assignment. Single quotes and the
    body of a heredoc with a quoted delimiter expand nothing and are skipped.
    One nested in another is found when its outer one is judged. None when a
    bracket is left open: unknown is not permission.
    """
    text = strip_quoted_heredocs(command)
    out, i, quote = [], 0, ""
    while i < len(text):
        ch = text[i]
        if ch == "\\" and quote != "'":
            i += 2
            continue
        if quote == "'":
            if ch == "'":
                quote = ""
            i += 1
            continue
        if ch == "'" and not quote:
            quote = "'"
            i += 1
            continue
        if ch == '"':
            quote = "" if quote == '"' else '"'
            i += 1
            continue
        # Process substitution is not one inside double quotes: there `->(`
        # is text, and only $( and backticks expand.
        if (ch == "$" or (ch in "<>" and not quote)) and text[i + 1:i + 2] == "(":
            depth, j, inner = 1, i + 2, ""
            while j < len(text) and depth:
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                if depth:
                    inner += text[j]
                j += 1
            if depth:
                return None
            out.append(inner)
            i = j
            continue
        if ch == "`":
            j = text.find("`", i + 1)
            if j == -1:
                return None
            out.append(text[i + 1:j])
            i = j + 1
            continue
        i += 1
    return out


def strip_quoted_heredocs(command):
    """The command without the bodies of heredocs whose delimiter is quoted."""
    lines = command.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for m in HEREDOC.finditer(line):
            delimiter = m.group(1) or m.group(2) or m.group(3)
            quoted = m.group(3) is None
            start = i
            while i < len(lines) and lines[i].strip() != delimiter:
                i += 1
            if not quoted:
                out.extend(lines[start:i])
            if i < len(lines):
                out.append(lines[i])
            i += 1
    return "\n".join(out)

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


# A package script, however it is spelled: `npm --silent run x`, `npm run
# --silent x`, `pnpm run x`, `yarn run x` and `bun run x` all run the script x,
# and a ban written as `npm run x` compared word by word missed every one but
# the first. Read as `npm run x …`, on both sides of the comparison.
MANAGERS = ("npm", "pnpm", "yarn", "bun")
MANAGER_VALUED = {"--prefix", "-C", "--dir", "-w", "--workspace", "--filter", "-F",
                  "--cwd", "--loglevel"}


def script_call(words):
    """The words with a package manager's script call read as `npm run x …`."""
    if not words or words[0] not in MANAGERS:
        return words

    def past_flags(i):
        while i < len(words) and words[i].startswith("-") and words[i] != "--":
            i += 2 if words[i] in MANAGER_VALUED and "=" not in words[i] else 1
        return i

    i = past_flags(1)
    if i >= len(words):
        return words
    # yarn, pnpm and bun also run a script named straight after them, with no
    # `run`: `pnpm db:promote` is the promote a ban on `npm run db:promote`
    # meant, and it went through. Read the same way on both sides, so a word
    # that is one of their own commands (`pnpm install`) only ever meets a ban
    # written in the same spelling.
    if words[i] not in ("run", "run-script", "rr"):
        if words[0] == "npm" or words[i] in ("exec", "dlx", "x", "create"):
            return words
        return ["npm", "run"] + words[i:]
    j = past_flags(i + 1)
    if j >= len(words):
        return words
    return ["npm", "run"] + words[j:]


# A shell handed the command as a string, or eval: the command is that string,
# and it is judged the same way. A code review found `bash -c 'gh pr merge 5'`
# and `eval gh pr merge 5` going through. Only the string is judged; a script
# file the shell is pointed at is not read, and that is the limit of a hook.
SHELLS = ("bash", "sh", "zsh", "dash", "ksh")


# The shell options that take the next word as their value: `bash -o pipefail
# -c '…'` reads `pipefail` as the option's, and the `-c` after it still counts.
SHELL_VALUED = ("-o", "+o", "-O", "+O")


def inner_command(words):
    """The command a shell or eval is told to run as a string, or None.

    `words` must keep their paths: the string is checked again as a command of
    its own, and `gh pr merge 5 --repo o/r` cut to last path parts was `r`.
    Only the shell's own name may be bare.
    """
    if not words:
        return None
    if words[0] == "eval":
        return " ".join(words[1:]) or None
    if words[0] in SHELLS:
        i = 1
        while i < len(words):
            w = words[i]
            if w in SHELL_VALUED:
                i += 2
                continue
            if w.startswith("-") and not w.startswith("--") and "c" in w[1:]:
                return words[i + 1] if i + 1 < len(words) else None
            if not w.startswith(("-", "+")):
                return None
            i += 1
    return None


# A redirection, the target stuck to it or not: `2>&1`, `>out`, `> out`, `<in`.
REDIRECTION = re.compile(r"^\d*(?:>>?|<|&>>?|>\|)(.*)$")


def strip_redirections(words):
    """The words without redirections and their targets: they are not
    arguments, and `git push origin 2>&1` read `2>` as a refspec."""
    out, skip = [], False
    for w in words:
        if skip:
            skip = False
            continue
        m = REDIRECTION.match(w)
        if m and out:
            skip = not m.group(1)
            continue
        out.append(w)
    return out


def closing_at(segment, braces=True):
    """The index of the word that closes a group, or None.

    Shared by both hooks: the step hook counted `)` word by word, and in
    `(cd ../main; x=$(git rev-parse HEAD); git push)` took `HEAD)` for the end
    of the subshell, and judged the push from outside it.

    A `)` closes a `$(` opened earlier before it closes a group, as in
    ungroup: shlex cuts `x=$(cat f)` into `x=$(cat` and `f)`.
    """
    subs = 0
    for k, w in enumerate(segment):
        if w == "}" and braces:
            return k
        subs += w.count("$(")
        closing = w.count(")") - w.count("(") + w.count("$(")
        while closing > 0 and subs:
            subs, closing = subs - 1, closing - 1
        if closing > 0:
            return k
    return None
