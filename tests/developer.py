#!/usr/bin/env python3
#
# A bench for developer.sh: who is running sclaude, and whether they maintain it.
#
# Nothing asked this before; everything was keyed by the feature or by the
# repository, which is right for one person and wrong the moment two people
# share a database or this repository. The name goes into an email address,
# a git branch and a JSON field, so a wrong one is not cosmetic: a dot breaks
# the address, a slash makes a branch nobody asked for.
#
# The cases, and what each would look like broken:
#
#   $SCLAUDE_DEV wins           a bench or a profile cannot pick a name.
#   git user.email              everybody is anonymous on a machine that commits.
#   global before checkout's    sclaude's own no-reply commit address renames
#                               the person in every product.
#   git sclaude.developer       a name set in ~/.profile only, and the bot and
#                               the systemd units naming somebody else.
#   nothing set                 an error where today's behaviour was wanted.
#   sanitising                  pwtest-ilia.p-...@example.com, dev/Ilia/x.
#   MAINTAINERS present         a stranger commits the orchestrator to main.
#   MAINTAINERS absent          a single-person copy refuses its own owner.
#
# Run it with: python3 tests/developer.py
import os
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")

failures = []


def check(name, got, want):
    if got == want:
        print("  PASS  %s" % name)
    else:
        failures.append(name)
        print("  FAIL  %s" % name)
        print("        want: %r" % (want,))
        print("        got:  %r" % (got,))


def git(repo, *args):
    subprocess.run(["git", "-C", repo] + list(args), check=True,
                   capture_output=True)


def run(body, instruments, env=None):
    """Run a snippet with developer.sh loaded against a scratch repository.

    HOME and the git config globals are pointed away so the machine's own
    identity cannot leak into a case that expects none.
    """
    script = 'set -uo pipefail\nINSTRUMENTS="%s"\nsource "%s/core/developer.sh"\n%s\n' % (
        instruments, LIB, body)
    full = {k: v for k, v in os.environ.items()
            if not k.startswith("GIT_") and k != "SCLAUDE_DEV"}
    full["HOME"] = instruments + "-home"
    full["GIT_CONFIG_NOSYSTEM"] = "1"
    full["GIT_CONFIG_GLOBAL"] = os.devnull
    if env:
        full.update(env)
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env=full)
    return done.stdout.strip()


with tempfile.TemporaryDirectory() as tmp:
    repo = os.path.join(tmp, "instruments")
    os.makedirs(repo)
    os.makedirs(repo + "-home")
    git(repo, "init", "-q")

    print("developer_name")
    check("empty-when-nothing-set", run("developer_name", repo), "")

    git(repo, "config", "user.email", "Ilia.Poliakov+work@Example.com")
    check("from-git-email-sanitised", run("developer_name", repo),
          "ilia-poliakov-work")

    # The checkout's own address signs commits to sclaude, often a forge's
    # no-reply one; the person is named by the address their products see.
    home_cfg = os.path.join(tmp, "global.gitconfig")
    with open(home_cfg, "w") as fh:
        fh.write("[user]\n\temail = alice@example.com\n")
    git(repo, "config", "user.email", "12345+alice@users.noreply.example.com")
    check("global-email-beats-checkout-own",
          run("developer_name", repo, {"GIT_CONFIG_GLOBAL": home_cfg}), "alice")
    check("checkout-own-still-signs-for-maintainers",
          run("developer_email", repo, {"GIT_CONFIG_GLOBAL": home_cfg}),
          "12345+alice@users.noreply.example.com")
    ident = os.path.join(tmp, "identity.gitconfig")
    with open(ident, "w") as fh:
        fh.write("[user]\n\temail = bob@example.com\n")
    with open(home_cfg, "w") as fh:
        fh.write("[include]\n\tpath = %s\n" % ident)
    check("global-email-through-include",
          run("developer_name", repo, {"GIT_CONFIG_GLOBAL": home_cfg}), "bob")
    # A conditional identity is judged against sclaude's checkout, whatever
    # the caller's directory: one answer for a session and for the bot.
    other = os.path.join(tmp, "elsewhere")
    os.makedirs(other)
    with open(home_cfg, "w") as fh:
        fh.write('[includeIf "gitdir:%s/"]\n\tpath = %s\n' % (repo, ident))
    check("conditional-include-judged-at-checkout",
          run("cd %s && developer_name" % other, repo, {"GIT_CONFIG_GLOBAL": home_cfg}), "bob")
    with open(home_cfg, "w") as fh:
        fh.write("[user]\n\temail =\n")
    check("empty-global-email-is-unset",
          run("developer_name", repo, {"GIT_CONFIG_GLOBAL": home_cfg}),
          "12345-alice")
    git(repo, "config", "user.email", "Ilia.Poliakov+work@Example.com")

    check("env-beats-git",
          run("developer_name", repo, {"SCLAUDE_DEV": "alice"}), "alice")
    check("env-sanitised-slash-and-case",
          run("developer_name", repo, {"SCLAUDE_DEV": "Bob/Smith."}), "bob-smith")
    git(repo, "config", "sclaude.developer", "Carol")
    check("git-key-beats-email", run("developer_name", repo), "carol")
    check("env-beats-git-key",
          run("developer_name", repo, {"SCLAUDE_DEV": "alice"}), "alice")
    git(repo, "config", "--unset", "sclaude.developer")
    check("sanitise-collapses-and-trims",
          run("developer_sanitize '..a__b..'", repo), "a-b")

    print("developer_is_maintainer")
    yes = 'developer_is_maintainer && echo yes || echo no'
    check("no-file-means-everybody", run(yes, repo), "yes")

    with open(os.path.join(repo, "MAINTAINERS"), "w") as fh:
        fh.write("# comment line\nilia.poliakov+work@example.com  # trailing\n")
    check("listed-case-insensitive", run(yes, repo), "yes")

    git(repo, "config", "user.email", "stranger@example.com")
    check("unlisted-is-not", run(yes, repo), "no")

    # A comment naming the address must not count as listing it.
    with open(os.path.join(repo, "MAINTAINERS"), "w") as fh:
        fh.write("# stranger@example.com asked to be added\n")
    check("commented-out-is-not", run(yes, repo), "no")

    git(repo, "config", "--unset", "user.email")
    check("empty-email-with-file-is-not", run(yes, repo), "no")

if failures:
    print("\n%d failed: %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("\nall passed")
