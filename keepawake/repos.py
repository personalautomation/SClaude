# keepawake's Telegram bot — the repositories the bot knows and their features:
# finding them, and what a repository's screen says about its main branch.
#
# Part of the bot that keepawake/telegramd.py runs.

import logging
import os
import re
import shlex

from keepawake.i18n import t
from keepawake.state import read
from keepawake import sessions, shell, status_report, topics


log = logging.getLogger("keepawake")


# The repositories whose features the bot can show. We search once per call:
# there are not many directories in $HOME, and projects do not lie deeper than
# the first level.
def known_repos():
    home = os.path.expanduser("~")
    found = []
    try:
        names = sorted(os.listdir(home))
    except OSError:
        return found
    for name in names:
        if name.startswith("."):
            continue
        path = os.path.join(home, name)
        if os.path.isdir(os.path.join(path, ".git")):
            found.append(path)
    return found


def repo_choice():
    # The choice lives in the state: the daemon survives restarts, and it has
    # nowhere else to remember which project the person looked at last.
    data = read()
    choice = data.get("sclaude_repo") or ""
    # The repository may have been renamed or deleted — the choice is then
    # invalid.
    if choice and os.path.isdir(os.path.join(choice, ".git")):
        return choice
    return ""


def repo_path(name):
    # Only a name from the list of known repositories. The name arrives in
    # callback_data and, although shlex.quote below stops it from executing as a
    # command, relying on escaping alone is unwise: checking against the list
    # closes off both directory traversal ("../..") and any future places this
    # name may end up in.
    for repo in known_repos():
        if os.path.basename(repo) == name:
            return repo
    return ""


def features_of_name(name):
    path = repo_path(name)
    if not path:
        return [], ""
    return features_of(path)


def features_of(repo):
    # A repository's features as parsed rows of the sclaude status table. We
    # parse them ourselves, because the menu's second level is buttons onto
    # features rather than text.
    out = status_report.strip_ansi(shell.run("cd %s && sclaude status" % shlex.quote(repo)))
    # git complains on stderr about repositories without origin/main — that has
    # nothing to do with features and must not get into the report.
    out = "\n".join(ln for ln in out.split("\n")
                    if not ln.startswith("fatal:")).strip()
    if not out or "No features in progress" in out:
        return [], out
    rows = []
    for line in out.split("\n"):
        line = line.rstrip()
        if line.startswith("FEATURE"):
            continue          # a table header will not do as a button
        if not line:
            # A blank line ends the feature table: below it sclaude prints the
            # branch breakdown ("Branches in progress"), and its rows are not
            # features. Without this a branch arrived in the menu as a separate
            # button leading nowhere.
            break
        # We split on two spaces — that is how align_columns separates the
        # columns. One will not do: a step's name is sometimes two words ("3/7
        # pull request"), and splitting on spaces returned "3/7 pull" as the step
        # and "request" as the path to the worktree. That is exactly how it
        # looked in the card.
        parts = [c for c in re.split(r" {2,}", line.strip()) if c]
        if len(parts) >= 2:
            # The columns: name, step, worktree. The path is not needed on the
            # button — it is long and eats the whole width on a phone, while the
            # table is there in full in the text below the buttons.
            wt = parts[2] if len(parts) > 2 else ""
            if wt and closing(wt):
                continue
            rows.append((parts[0], parts[1], wt))
    return rows, out


def closing(wt):
    """Whether a feature's worktree is being removed: stop_dev marks it before
    the minute git takes to delete it, and from then on the feature is gone
    for the menu — a card offered then leads into a tree half deleted."""
    return os.path.exists(os.path.join(wt, ".sclaude", "local", "feature", topics.CLOSING_MARK))


def gh_slug(repo):
    # The repository's owner/name from origin's address. We parse it ourselves
    # rather than asking `gh repo view`: that is a network call for the sake of a
    # string that sits in the config.
    url = shell.run("git -C %s remote get-url origin" % shlex.quote(repo)).strip()
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else ""


def commit_links(repo, commit):
    # GitHub links from the last commit.
    #
    # The number in a merge commit is the PR, not the issue: "Merge pull
    # request #89" leads to the pull request. The issue itself hides a line
    # deeper, in that same PR's body ("Closes #20") — that is, where sclaude's
    # step 3 puts it. The branch's name (feat/20-change-…) holds the same number
    # and will do when the body is not to hand.
    #
    # Hence two different questions and two different links: "what change has
    # arrived" and "why it was needed". The second is the more valuable — the
    # statement lies in the issue — and without it the card made people look for
    # it by hand.
    #
    # All best-effort: no gh, no network, the number was not found — there will
    # simply be no link. A repository's card is not the place to fall over.
    slug = gh_slug(repo)
    if not slug:
        return []

    m = re.search(r"#(\d+)", commit or "")
    if not m:
        return []
    pr = m.group(1)
    links = [(t("repo.pr", n=pr), "https://github.com/%s/pull/%s" % (slug, pr))]

    body = shell.run("gh pr view %s -R %s --json body -q .body" % (shlex.quote(pr), shlex.quote(slug)),
               timeout=20)
    issue = ""
    found = re.search(r"(?:clos(?:e|es|ed)|fix(?:e|es|ed)?|resolv(?:e|es|ed))\s+#(\d+)",
                      body or "", re.I)
    if found:
        issue = found.group(1)
    else:
        # The fallback is the PR's branch name: sclaude names it after the
        # issue's number, so the number is there even for a PR with an empty
        # body.
        head = shell.run("gh pr view %s -R %s --json headRefName -q .headRefName"
                   % (shlex.quote(pr), shlex.quote(slug)), timeout=20)
        m2 = re.match(r"^[a-z]+/(\d+)-", (head or "").strip())
        if m2:
            issue = m2.group(1)
    if issue:
        links.append((t("repo.issue", n=issue),
                      "https://github.com/%s/issues/%s" % (slug, issue)))
    return links


def links_line(links):
    # The links as a line under the commit. Telegram makes a link of an
    # <a href>, and the caption "#20" is shorter than a bare address — on a phone
    # that is the difference between one line and three.
    if not links:
        return ""
    return "\n" + " · ".join('<a href="%s">%s</a>' % (url, status_report.escape(label))
                             for label, url in links)


def main_branch_state(repo):
    # When there are no features there is no reason to show emptiness: the
    # person opened the repository to learn something about it. The main branch
    # is the little that can always be said, and it answers the question "what
    # state is the project in".
    q = shlex.quote(repo)
    branch = shell.run("git -C " + q + " rev-parse --abbrev-ref HEAD").strip()
    commit = shell.run("git -C " + q + " log -1 --format='%h %s'").strip()
    when = shell.run("git -C " + q + " log -1 --format=%cr").strip()
    dirty = shell.run("git -C " + q + " status --porcelain")
    dirty_n = 0 if dirty == t("cmd.empty") else len([l for l in dirty.split("\n") if l.strip()])
    ahead = shell.run("git -C " + q + " rev-list --count @{u}..HEAD 2>/dev/null").strip()
    try:
        ahead_n = int(ahead)
    except ValueError:
        ahead_n = 0          # no upstream — nothing to compare against

    # A fresh repository with no commits: git answers with a complaint on
    # stderr, and there is no reason to show it to a person — "there are no
    # commits yet" is not an error but a state that can be put in words.
    empty = ("fatal:" in commit) or ("fatal:" in branch) or ("fatal:" in when)

    extra = []
    if dirty_n:
        extra.append(t("repo.dirty", n=dirty_n))
    if ahead_n:
        extra.append(t("repo.ahead", n=ahead_n))
    if not extra:
        extra.append(t("repo.clean"))
    return {"branch": branch or "?", "commit": commit or "?",
            "when": when or "", "extra": "\n".join(extra), "empty": empty,
            "links": "" if empty else links_line(commit_links(repo, commit))}


def repo_text(name):
    # raw is the whole sclaude status table; it is no longer needed here, but
    # features_of_name returns it along with the rows, and it has to be parsed
    # for the buttons' sake anyway.
    feats, _raw = features_of_name(name)
    if not feats:
        path = repo_path(name)
        if not path:
            return t("repo.norepos")
        st = main_branch_state(path)
        if st["empty"]:
            return t("repo.nocommits", name=status_report.escape(name), extra=st["extra"])
        return t("repo.none", name=status_report.escape(name),
                 branch=status_report.escape(st["branch"]), commit=status_report.escape(st["commit"]),
                 when=status_report.escape(st["when"]), extra=st["extra"],
                 links=st["links"])
    body = t("repo.count", name=status_report.escape(name), n=len(feats))
    # A button goes to the first eight (see features_keyboard). The rest are
    # not visible in the chat at all — neither as a button nor as a line — so a
    # counter over emptiness would only mislead: "features in progress: 9" with
    # eight of them there. We name them.
    rest = [r[0] for r in feats[sessions.FEATURE_BUTTONS:]]
    if rest:
        body += t("repo.rest", rest=status_report.escape(", ".join(rest)))
    return body
