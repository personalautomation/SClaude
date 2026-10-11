#!/usr/bin/env python3
#
# The bans of steps 2-4 that --disallowed-tools cannot express.
#
# Most of the bans live as a flag: `Bash(vercel:*)` and the like are read
# straight from sclaude's command line, and that is enough. Only what the flag
# breaks on ends up here — verified live, not from the documentation:
#
#   * "push is allowed, but not to main". A rule with a `*` in the middle —
#     `Bash(git push * main)` — does not fire at all, and `git push` cannot be
#     banned outright: step 2 pushes the branch, step 4 pushes review fixes. So
#     the arguments have to be parsed, and that is a hook's work.
#
#   * `--force` and `--no-verify` — the same arguments of the same command.
#
#   * The form with a path. `Bash(gh pr merge:*)` lets `/usr/bin/gh pr merge`
#     through; here the command's name is compared by basename, and a path does
#     not help. The flag and the hook therefore overlap deliberately: the flag
#     closes the direct form and is visible to the human, the hook closes the
#     way around.
#
#   * `supabase db push`. The ban on it depends not on the command but on which
#     environment the tree is looking at — a flag does not express that at all.
#     More at DB_PUSH below.
#
#   * `vercel`. The ban depends on the subcommand: deploying is the human's
#     step, while `vercel env ls` reads a value and changes nothing. A flag bans
#     the name or nothing, so it banned the read too — and a fixing session lost
#     its investigation to that. More at VERCEL_READS below.
#
#   * A package runner. `npx vercel --prod` and `bunx vercel --prod` are that
#     same deploy, and `Bash(npx vercel:*)` matched neither the runner's flags
#     (`npx -y vercel`) nor a version in the name (`vercel@59.17.0`) nor an
#     assignment before it. Stripped in _shell.strip_runners.
#
# A double space does not trouble the flag — it catches `gh  pr view`, verified.
# That is not the hole to plug here.
#
# The parsing is the same as in no-code-in-planning.py, and now literally the
# same: `_shell.tokenize` cuts the string. While the parsing was copied, the
# hooks could diverge silently — and they did: a `;` without spaces stayed a
# separator in words only, and `echo hi;gh pr merge` went past the ban.
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from _friction import note
from _shell import GIT_VALUED, SEPARATORS, script_call, strip_runners, strip_wrappers, tokenize, ungroup
import policy as policy_lib  # noqa: E402 — sclaude/lib/policy.py
import envs as envs_lib  # noqa: E402 — sclaude/lib/envs.py

# The branch that must not be pushed to: it moves only by merging a PR.
PROTECTED = "main"

# The commands banned by prefix come from the session's policy: sclaude's
# presets, the product's team rules and the person's own (sclaude/lib/policy.py).
# The flag catches their direct form; this hook catches the form with a path or
# behind a wrapper. The rules below that need more than a prefix are code, and
# the policy says which of them are on.
POLICY = {"deny": [], "allow": [], "rules": [], "lifted": []}


def rule_on(name, words=None):
    """Whether a rule of an integration applies to this call.

    A team's `allow` lifts an integration's rule for the commands it names.
    """
    if name not in POLICY.get("rules", []):
        return False
    if words and any(tuple(words[:len(l)]) == tuple(l) for l in POLICY.get("lifted", [])):
        return False
    return True


# `supabase db push` is the only ban that depends not on the command but on
# where it will go. It used to stand in the table above, unconditionally, and
# that caught real trouble exactly one time in two: the first refusal fell on an
# environment set to prod and was to the point; the second came after the tree
# had been switched to dev and confirmed as dev, and said "this is the same
# prod" about a command that was going to dev. The project had no other way to
# apply a migration to dev, and its own docs named `supabase db push` as the
# one. The ban closed a documented path without offering a replacement, and
# the step applied the migration around the CLI, writing the migration history
# by hand — exactly the class of "something got into the database by another
# route" that a project's migration checks are written against.
DB_PUSH = (("npx", "supabase", "db", "push"), ("supabase", "db", "push"))

DB_PUSH_REASON = ("this environment is protected (or could not be identified) — "
                  "applying a migration here bypasses the project's own way of doing it")

# `vercel` is the one ban that depends on the subcommand, which is why it is a
# function below rather than a line in the table above.
#
# It used to stand there unconditionally, and the flag banned the name as well.
# That refused `vercel env ls preview` — a read that deploys nothing — to a
# session repairing a red preview regression: it needed a Preview variable's
# value to tell "the deployment points at another bucket" from "the keys no
# longer open this one". It gave up, and the human ran the command by hand while
# the feature stood. Reading the environment is exactly how a deployed stage's
# failure is told apart from the branch's, and it is the one thing a fixing
# session cannot get from the worktree.
#
# An allowlist rather than a list of banned subcommands: whatever Vercel adds
# next is a deploy until somebody says otherwise. A bare `vercel`, and `vercel`
# with flags alone, is a deploy — that is the CLI's default — so it needs no
# entry here and falls through to the ban.
# `rollback status` is a read like the rest: it answers whether a rollback is
# in flight and moves nothing. A session looking at a red production regression
# has a real reason to ask — the same class of read as `vercel env ls preview`,
# which this list was widened for once already. The lookup below tries the
# two-word prefix before the one-word one, so it matches ahead of a bare
# `rollback`, which stays banned.
VERCEL_READS = {
    ("env", "ls"), ("inspect",), ("ls",), ("list",), ("logs",),
    ("whoami",), ("teams", "ls"), ("project", "ls"), ("projects",),
    ("domains", "ls"), ("certs", "ls"), ("dns", "ls"),
    ("rollback", "status"), ("promote", "status"),
}

VERCEL_REASON = ("deploying is the human's step; the orchestrator offers "
                 "preview itself, from the main repository, where the project "
                 "link lives. Rolling production back is the orchestrator's "
                 "too — from the red-prod path or `sclaude rollback`, where "
                 "the deployment to go back to is on record and the branch's "
                 "migrations are classified first. Reading is allowed: env ls, "
                 "inspect, ls, logs, rollback status")


def vercel_refuses(words):
    """The reason this `vercel` call is banned, or None."""
    if not words or words[0] != "vercel" or not rule_on("vercel-deploy", words):
        return None
    # The subcommand is the first word that is not a flag. `--scope my-team`
    # and `--token x` carry a value, but a value is never a subcommand's name
    # here: a read is named by its own first word, so the longest prefix that
    # matches the allowlist decides.
    rest = [w for w in words[1:] if not w.startswith("-")]
    for length in (2, 1):
        if tuple(rest[:length]) in VERCEL_READS:
            return None
    return VERCEL_REASON


def active_environment(cwd):
    """The environment this tree is on, or None when there is no settled answer.

    The tree's .env.local names the environment, by the file it points at,
    and the Supabase CLI's link has to agree with it, since `supabase db push`
    obeys the link (envs.settled). No answer is not permission: a product that
    names no environments has none, and every environment counts as protected.
    """
    return envs_lib.settled(cwd, cwd)


def project_dir():
    """The repository this hook is deciding about.

    The step's session sets CLAUDE_PROJECT_DIR to its worktree's root, and that
    is the answer whenever it is there. `os.getcwd()` is the fallback for a hook
    run outside one, where it is the only clue available.
    """
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def environment_is_protected(cwd, name):
    """Whether the product marks this environment protected, in the tree's
    .sclaude/config.json. True for anything that cannot be resolved: the
    question is "may a migration be applied here", and an environment that
    cannot be identified is exactly the case the ban exists for."""
    return not name or envs_lib.protected(cwd, name)


# A tree is on the environment whose file its .env.local points at
# (envs.py), so pointing it at production's file is the switch to production:
# the next step's server, checks and database calls would all work there
# without anybody seeing it. A product's own switch script is named in its
# policy; this is the one every product shares.
ENV_SWITCH_REASON = ("this points .env.local at production's environment file, and the "
                     "next step would work against production without knowing it")


def env_switch_refuses(words, raw):
    """The reason this `ln` or `cp` onto .env.local is banned, or None."""
    if not words or words[0] not in ("ln", "cp", "install"):
        return None
    paths = [w for w in raw[1:] if not w.startswith("-")]
    if not paths or os.path.basename(paths[-1].rstrip("/")) != ".env.local":
        return None
    tree = project_dir()
    prod = envs_lib.production(tree)
    target = envs_lib.env_file(tree, prod) if prod else None
    if not target:
        return None
    name = os.path.basename(target)
    if any(os.path.basename(p) == name for p in paths[:-1]):
        return ENV_SWITCH_REASON
    return None


DB_URL_REASON = ("--db-url points the push at a database named on the command "
                 "line rather than the one this tree is on, so the tree's environment "
                 "says nothing about where it lands; only a local database may be "
                 "named that way")
LOCAL_DB = re.compile(r"^[a-z]+://[^@/]*@?(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(/|$)")


def db_push_refuses(words, raw=None):
    """The reason this `supabase db push` is banned, or None.

    `raw` is the same call with its words unstripped: a URL is a path to the
    stripping, which would leave only its last part.
    """
    if not any(tuple(words[:len(p)]) == p for p in DB_PUSH):
        return None
    if not rule_on("supabase-db-push", words):
        return None
    # A target named on the command line overrides the tree's: a review found
    # `supabase db push --db-url <production>` allowed on a tree that was on
    # dev. Only a local database passes, and an address that cannot be read
    # (a variable, a substitution) is not one.
    full = raw or words
    for i, word in enumerate(full):
        if word == "--db-url" or word.startswith("--db-url="):
            url = word.split("=", 1)[1] if "=" in word else (full[i + 1] if i + 1 < len(full) else "")
            # A local database named outright is the one place the push goes,
            # whatever the tree is on.
            return None if LOCAL_DB.match(url) else DB_URL_REASON
    # Any environment the project does not protect, rather than the literal
    # "dev" this used to name.
    #
    # The literal was right while dev was the only database a feature could be
    # pointed at. It stopped being right the moment a developer could run
    # Supabase locally or work under the `preview` name: both are ordinary
    # places to apply a migration, and both would have been refused here with a
    # message about prod. That is the same failure the comment above DB_PUSH
    # describes — a ban closing a documented path and sending the step around
    # the CLI — repeated on the environments that came later.
    #
    # Silence still means a ban: an unknown environment is not permission but
    # precisely the case the ban was written for.
    #
    # CLAUDE_PROJECT_DIR first, `os.getcwd()` only as a fallback. Both of the
    # things read below — the product's environment command and its file of
    # environments (`environments` in .sclaude/config.json) — are repository-relative, and the working
    # directory is not reliably the repository: the friction review session runs
    # these hooks by hand to check a fix, and `cd`s into a feature's tree while
    # doing so. `_friction.py` records that incident at length and resolves the
    # same way. Getting it wrong here fails closed — an unreadable config reads
    # as protected — so the symptom would be `supabase db push` refused with a
    # reason that does not fit, which is the kind of ban nobody can act on.
    cwd = project_dir()
    if not environment_is_protected(cwd, active_environment(cwd)):
        return None
    return DB_PUSH_REASON


# A feature with a local Supabase of its own (sclaude/lib/featuredb.sh) runs
# with SUPABASE_WORKDIR pointing at it, so a bare `supabase db reset` rebuilds
# this feature's database and nobody else's. `--workdir` is the one way to point
# the CLI past that — at the main repository's stack, which is every other
# feature's fallback and the developer's own data, or at another feature's. A
# reset there is not recoverable, and nothing in a step needs another stack.
WORKDIR_REASON = ("this feature has its own local Supabase, and SUPABASE_WORKDIR "
                  "already points the CLI at it; --workdir would reach another "
                  "stack — the main repository's or another feature's. Drop the "
                  "flag")


def workdir_refuses(command):
    """The reason this `supabase --workdir` is banned, or None.

    Read from the raw command rather than from segments(): the shared tokenizer
    keeps only the last component of a path — it exists to name programs — and
    here the path is the whole question."""
    own = os.environ.get("SUPABASE_WORKDIR")
    if not own or not rule_on("supabase-workdir"):
        return None
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    if not any(os.path.basename(w) == "supabase" for w in words):
        return None
    for i, word in enumerate(words):
        if word == "--workdir":
            target = words[i + 1] if i + 1 < len(words) else ""
        elif word.startswith("--workdir="):
            target = word.split("=", 1)[1]
        else:
            continue
        path = os.path.realpath(os.path.join(project_dir(), os.path.expanduser(target)))
        if path != os.path.realpath(own):
            return WORKDIR_REASON
    return None


# A schema change aimed at a shared cloud project rather than the local
# database. Not a ban — the cloud dev project is a legitimate place, and a
# person may mean it — but a question: work that touches the database belongs on
# the project's local environment, where every feature has a database of its
# own (sclaude/lib/featuredb.sh), and a migration pushed to the shared project
# lands under everybody else's features. The protected environments stay with
# db_push_refuses, which refuses them outright.
#
# Only what reaches the linked project: `db push` always does; `migration up`
# and `db reset` do only with --linked, and without it they touch the local
# stack, which is the point.
SHARED_SCHEMA_ASK = ("this changes the schema of \"{name}\", a database the whole team "
                     "shares — their features see your migration at once. Work that "
                     "touches the database belongs on \"{local}\", where this feature "
                     "has a database of its own: switch the tree to it first. Go ahead "
                     "only if the shared project is really what you mean.")


def local_environment(cwd):
    """The project's local environment, from .sclaude/config.json, or None."""
    try:
        with open(os.path.join(cwd, ".sclaude/config.json")) as fh:
            config = json.load(fh)
    except (OSError, ValueError):
        return None
    local = ((config.get("database") or {}).get("local") or {}).get("environment")
    return local if isinstance(local, str) and local else None


def shared_schema_asks(command):
    """The question to put before a schema change on a shared project, or None."""
    parts = segments(command)
    if not parts or not rule_on("supabase-shared"):
        return None
    for words in parts:
        if words[:1] != ["supabase"]:
            continue
        rest = words[1:]
        linked = "--linked" in rest
        if not (rest[:2] == ["db", "push"]
                or (rest[:2] == ["migration", "up"] and linked)
                or (rest[:2] == ["db", "reset"] and linked)):
            continue
        cwd = project_dir()
        local = local_environment(cwd)
        if not local:
            return None
        name = active_environment(cwd)
        # Unresolved or protected is db_push_refuses' business, and it refuses.
        if not name or name == local or environment_is_protected(cwd, name):
            return None
        return SHARED_SCHEMA_ASK.format(name=name, local=local)
    return None


TAIL = ("  Tell the human and stop — the next move is theirs.")


def segments(command, raw=False):
    """The command split on | && ; into separate calls, each without wrappers.

    Returns a list of lists of words. Something unparsable (an unclosed quote)
    gives None: such a string cannot be judged, and it cannot be let through
    blindly either. With `raw` the words are kept as they are: stripping cuts
    the path off every word, and `cd` and a push's remote need theirs.
    """
    tokens = tokenize(command)
    if tokens is None:
        return None

    out, current = [], []
    for token in tokens:
        if token in SEPARATORS:
            if current:
                out.append(current)
            current = []
            continue
        current.append(token)
    if current:
        out.append(current)

    # Wrappers come in chains (`setsid nohup npm …`) and carry their own
    # arguments with them: without this `timeout 5 gh pr merge` left "5" as the
    # first word, and the whole ban table missed. The parsing is shared with
    # step 1's hook — see strip_wrappers in _shell.py.
    #
    # And then the package runners: `npx vercel --prod` is a deploy to prod
    # however it is spelled, and the table compares the first word. Separate
    # from strip_wrappers because step 1's hook must keep seeing `npx` itself —
    # see RUNNERS in _shell.py.
    if raw:
        return out
    trimmed = []
    for words in out:
        stripped = strip_runners(strip_wrappers(words))
        if stripped:
            trimmed.append(stripped)
    return trimmed


# A push to `main` that cannot reach the project's remote is not the push the
# ban is about. A review subagent once built a throwaway repository in
# its scratchpad — `git init --bare o.git`, `git remote add origin ../o.git` —
# to see how git fails on a broken config, and `git push -q origin main` there
# was refused with "tell the human and stop". The feature reads `main` from git,
# so `main` was the natural branch to test with; the session got by renaming it,
# and a less resourceful one would have stopped.
#
# So a push to `main` passes only from a directory under the temp root, where
# every scratchpad lives and the project never does, and only when nothing in
# sight is a network address: not the remote argument, not any word of the
# command (a `git clone https://…` before the push), not the URL an existing
# repository there has for that remote (a clone made by an earlier command).
TEMP_ROOT = os.path.realpath(tempfile.gettempdir())

# An address git reaches over the network: a URL other than file://, or the scp
# form `user@host:path`.
NETWORK_WORD = re.compile(r"(?<!file)://|[\w.-]+@[\w.-]+:")


def network(address):
    """Is this remote argument (a name resolved, or a path, or a URL) remote?"""
    if address.startswith("file://"):
        return False
    if "://" in address:
        return True
    # `host:path` with no slash before the colon is ssh to git.
    return ":" in address.split("/", 1)[0]


def remote_url(where, remote):
    """The URL an existing repository has for this remote, or None."""
    try:
        done = subprocess.run(["git", "-C", where, "remote", "get-url", remote],
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


# The commands that give a repository its remotes.
REMOTE_SETTERS = (("git", "remote", "add"), ("git", "remote", "set-url"),
                  ("git", "clone"), ("git", "config"))


def hidden_remote(parts):
    """Does a command that sets a remote take its address from a variable?"""
    return any(tuple(words[:len(p)]) == p
               and any("$" in w or "`" in w for w in words)
               for words in parts for p in REMOTE_SETTERS)


def scratch_push(command, parts, where, remote, redirected=False):
    """Is this a push into a throwaway repository under the temp root?"""
    if not where or not remote:
        return False
    if os.path.exists(where):
        where = os.path.realpath(where)
    project = os.path.realpath(project_dir())
    if TEMP_ROOT in ("/", project) or project.startswith(TEMP_ROOT + os.sep):
        return False
    if not where.startswith(TEMP_ROOT + os.sep):
        return False
    # The repository can be redirected by name, past the directory we follow:
    # by GIT_DIR in the environment, set before the push or on it, or by the
    # push's own `--git-dir` (see refuses and git_globals). Not by `--git-dir`
    # on another git call elsewhere in the command — it is a flag of that one
    # call. One review session had it in a heredoc, a script written to a
    # file after the push, and the push was refused.
    if redirected:
        return False
    if NETWORK_WORD.search(command):
        return False
    if "/" in remote or ":" in remote:
        return not network(remote)
    if os.path.isdir(where):
        url = remote_url(where, remote)
        if url is not None:
            return not network(url)
    # The remote does not exist yet, so this command adds it, and nothing in
    # it is a network address — unless it comes from a variable.
    return not hidden_remote(parts)


# A variable set to a literal earlier in the same command is as known as the
# literal itself. A review session wrote `S=/tmp/…/scratchpad/r2; cd $S/w`
# before its scratch push to main, and the unresolved `$S` kept the refusal.
ASSIGNMENT = re.compile(r"([A-Za-z_]\w*)=(.*)", re.S)
VARIABLE = re.compile(r"\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))")


def remember(known, words):
    """Record the variables a segment of bare assignments sets.

    Only a segment that is nothing but `NAME=value` words, with an optional
    `export` in front, persists in bash; `S=x cmd` lives for that command only.
    A value with a substitution in it is not known, and forgets the name.
    """
    if words[:1] == ["export"]:
        words = words[1:]
    pairs = [ASSIGNMENT.fullmatch(w) for w in words]
    if not words or not all(pairs):
        return
    for match in pairs:
        name, value = match.groups()
        if any(c in value for c in "$`("):
            known.pop(name, None)
        else:
            known[name] = value


def expand(path, known, command):
    """The path with known variables put in, or None when one is unknown."""
    def put(match):
        name = match.group(1) or match.group(2)
        # Quotes are gone from the words, so `cd '$S'` looks the same as
        # `cd $S` here; bash takes the first literally. Refuse to guess.
        if name not in known or any(VARIABLE.search(q) for q in
                                    re.findall(r"'[^']*'", command)
                                    if name in q):
            raise KeyError(name)
        return known[name]
    try:
        return VARIABLE.sub(put, path)
    except KeyError:
        return None


def follow_cd(where, words, known=None, command=""):
    """The directory after this segment, or None when it cannot be told.

    Only a plain `cd <path>` is followed. No argument, `-`, `~`, a variable
    nobody set to a literal earlier in the command, a subshell bracket or
    pushd/popd make the directory unknown, and an unknown directory never
    counts as scratch.
    """
    if any("(" in w or ")" in w for w in words):
        return None
    if words[0] in ("pushd", "popd"):
        return None
    if words[0] != "cd":
        return where
    if len(words) != 2:
        return None
    path = words[1]
    if "$" in path and known:
        path = expand(path, known, command)
        if path is None:
            return None
    if path.startswith(("-", "~")) or "$" in path or "`" in path:
        return None
    if os.path.isabs(path):
        return os.path.normpath(path)
    if where is None:
        return None
    return os.path.normpath(os.path.join(where, path))


MAIN_REASON = ("main moves only by merging a pull request — that is "
               "the GitHub flow of this project")


def push_target(ref, known):
    """Where a refspec pushes to, as a branch name; None when it cannot be told.

    The destination is the right-hand side, and git takes it in more than one
    spelling: `+HEAD:main` forces it, `HEAD:refs/heads/main` names it in full.
    A variable set to a literal earlier in the command is put in; one that is
    not, or a command substitution, leaves the destination unknown — and an
    unknown destination is treated as main. A code review found
    `x=main; git push origin HEAD:$x` and `git push origin $(echo main)` going
    through.
    """
    target = ref.split(":")[-1].lstrip("+")
    if "$(" in target or "`" in target or ")" in target:
        return None
    if "$" in target:
        target = expand(target, known, "") if known else None
        if target is None:
            return None
    if target.startswith("refs/heads/"):
        target = target[len("refs/heads/"):]
    return target


def push_refuses(words, command="", parts=(), where=None, raw=(),
                 redirected=False, known=None):
    """The reason this `git push` is banned, or None."""
    if words[:2] != ["git", "push"]:
        return None

    flags = [w for w in words[2:] if w.startswith("-")]
    for flag in flags:
        if flag in ("--force", "-f") or flag.startswith("--force-with-lease"):
            return ("a reviewer is reading this branch, and rewritten "
                    "history strands the discussion")
        if flag == "--no-verify":
            return ("--no-verify bypasses .githooks/pre-push, which exists "
                    "precisely to catch the database drifting from the repo")

    # The positional arguments: the remote's name and the refspecs. We count
    # both `git push origin main` and `git push origin HEAD:main` as a push to
    # main — in a refspec the right-hand side is what matters, and it is the
    # destination branch.
    refs = [w for w in words[2:] if not w.startswith("-")]
    # The remote with its path, from the same words before stripping.
    remote = [w for w in raw[len(raw) - len(words) + 2:] if not w.startswith("-")]
    if remote and scratch_push(command, parts, where, remote[0], redirected):
        return None
    for ref in refs[1:] if len(refs) > 1 else []:
        target = push_target(ref, known or {})
        if target is None:
            return ("the push's destination is built at run time, so it cannot "
                    "be told from main; " + MAIN_REASON)
        if target == PROTECTED:
            return MAIN_REASON
    # `git push main` without a remote name is an attempt too, crooked as it
    # is. Any other lone word is the remote — `git push "$REMOTE"` included,
    # which an unknown value used to refuse as a push to main.
    if len(refs) == 1 and refs[0] == PROTECTED:
        return MAIN_REASON
    # With no refspec git pushes the branch checked out, so `git push` or
    # `git push origin` on main is the push to main. It went through, because
    # only refspecs were read. A directory that cannot be told is left alone,
    # as it was before.
    if len(refs) <= 1 and where and current_branch(where) == PROTECTED:
        return MAIN_REASON
    return None


def current_branch(where):
    """The branch checked out in a directory, or None."""
    try:
        done = subprocess.run(["git", "-C", where, "symbolic-ref", "--short", "-q", "HEAD"],
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


# The merge through the API rather than `gh pr merge`: the REST endpoint takes
# it as a PUT (a GET on the same path only asks whether it is merged), and
# GraphQL as the mergePullRequest mutation. A code review found both going
# through.
MERGE_PATH = re.compile(r"(^|/)repos/[^/]+/[^/]+/pulls/[^/]+/merge/?$")
MERGE_REASON = "merging is the human's step — gh pr merge, through the API or not"


def api_merge_refuses(words, raw):
    """The reason this `gh api` call is banned, or None.

    `raw` is the same call with its words unstripped: the endpoint is a path,
    and stripping leaves only its last part.
    """
    if words[:2] != ["gh", "api"]:
        return None
    rest = raw[2:]
    if any("mergePullRequest" in w for w in rest):
        return MERGE_REASON
    put = False
    for i, w in enumerate(rest):
        if w in ("-X", "--method") and i + 1 < len(rest) and rest[i + 1].upper() == "PUT":
            put = True
        elif w.upper() in ("-XPUT", "--METHOD=PUT"):
            put = True
    if put and any(MERGE_PATH.search(w) for w in rest):
        return MERGE_REASON
    return None


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


# Grouping brackets are taken off by ungroup(), in _shell.py: write-guard.py
# reads groups the same way.


# git's own options, the ones before the subcommand. `git -C ~/myapp push
# origin main` is the push to main however it is spelled, and so are
# `git --git-dir=… push` and `git -c k=v push`; a friction review found that
# every check below compared the first two words with `git push`,
# so all of them — main, --force, --no-verify — went through with any of these
# in front.
#
# The options that take their value as the next word are GIT_VALUED, in
# _shell.py: write-guard.py reads git calls the same way.


def git_globals(raw, where):
    """git's options before the subcommand, read off one call.

    `raw` is the call with its paths, starting at `git`. Returns how many words
    the options take, the directory the call runs in (`-C`, followed like `cd`;
    None when it cannot be told), and whether the repository is named past the
    directory (`--git-dir`, `--work-tree`, or a `-c` that could set a remote) —
    such a call is never a scratch push.
    """
    i, redirected = 1, False
    while i < len(raw) and raw[i].startswith("-"):
        name, has_value, value = raw[i].partition("=")
        if name in GIT_VALUED and not has_value:
            value = raw[i + 1] if i + 1 < len(raw) else ""
            i += 2
        else:
            i += 1
        if name == "-C":
            where = follow_cd(where, ["cd", value]) if value else None
        elif name in ("--git-dir", "--work-tree", "-c", "--config-env"):
            redirected = True
    return i - 1, where, redirected


def refuses(command, step, cwd=None, depth=0):
    """The reason to refuse this command, or None."""
    parts = segments(command)
    if parts is None:
        return "the command could not be parsed, and the step's bans outweigh convenience"

    reason = workdir_refuses(command)
    if reason:
        return reason

    table = {tuple(script_call(list(d["words"]))): d["why"] for d in POLICY.get("deny", [])}

    where = os.path.realpath(cwd or os.getcwd())
    known = {}
    redirected = False
    grouped = False
    for raw in segments(command, raw=True):
        flat, bracket = ungroup(raw)
        remember(known, flat)
        redirected = redirected or any("GIT_DIR" in w for w in raw)
        where = None if grouped else follow_cd(where, raw, known, command)
        grouped = grouped or bracket
        raw = flat
        words = strip_runners(strip_wrappers(raw))
        if not words:
            continue
        # The string a shell or eval runs, from the words as written: the ones
        # above are cut to their last path part, all but the command's name.
        inner = inner_command(words[:1] + raw[len(raw) - len(words) + 1:])
        if inner is not None:
            # Deep enough for any honest use; a string nested further than this
            # is refused rather than followed.
            if depth >= 3:
                return "a command nested this deep cannot be judged"
            reason = refuses(inner, step, where, depth + 1)
            if reason:
                return reason
            continue
        # `-C` moves this call only, so the directory the next segment starts
        # in stays `where`.
        here, also = where, False
        if words[0] == "git":
            taken, here, also = git_globals(raw[len(raw) - len(words):], where)
            words = words[:1] + words[1 + taken:]
        reason = (push_refuses(words, command, parts, here, raw,
                               redirected or also, known)
                  or api_merge_refuses(words, raw[len(raw) - len(words):])
                  or db_push_refuses(words, raw[len(raw) - len(words):])
                  or env_switch_refuses(words, raw[len(raw) - len(words):])
                  or vercel_refuses(words))
        if reason:
            return reason
        called = script_call(words)
        for prefix, why in table.items():
            if tuple(called[:len(prefix)]) == prefix:
                return why
    return None


def deny(reason, step="", subject=""):
    # The refusal reaches the log: between steps the review session will go
    # through it and decide whether the ban was deliberate or is getting in the
    # way by oversight.
    note(step, "hook", subject, reason)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason + TAIL,
        }
    }, ensure_ascii=False))
    sys.exit(0)


def flag(argv, name):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return ""


argv = sys.argv[1:]
step = flag(argv, "--step")
# The product and the person whose policy this session works under. steps.sh
# passes both; without a root the hook works out the repository it runs in.
root = flag(argv, "--root")
if not root:
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                cwd=project_dir(), capture_output=True, text=True, timeout=5)
        root = os.path.dirname(common.stdout.strip()) if common.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        root = ""
POLICY = policy_lib.merged(root, flag(argv, "--person"), step)

try:
    payload = json.load(sys.stdin)
except ValueError:
    # Parsing the input did not work out: we pass rather than ban at random.
    # The same choice as in no-code-in-planning.py, and for the same reason.
    sys.exit(0)

if payload.get("tool_name") == "Bash":
    command = str((payload.get("tool_input") or {}).get("command", ""))
    # A hook that raises exits non-zero, and Claude Code runs the command
    # anyway: an error here let every ban go. Refused instead, as a command
    # that cannot be parsed is: the step's bans outweigh convenience.
    try:
        reason = refuses(command, step, payload.get("cwd"))
    except Exception as exc:  # noqa: BLE001
        reason = "the ban check failed on this command (%s: %s), so it is refused" % (
            type(exc).__name__, exc)
    if reason:
        deny(reason, step, command)
    question = shared_schema_asks(command)
    if question:
        # Asked of the person at the terminal rather than refused: not our
        # refusal, so not in the friction log either.
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": question,
            }
        }, ensure_ascii=False))
        sys.exit(0)

sys.exit(0)
