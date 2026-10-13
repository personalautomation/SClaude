#!/usr/bin/env python3
#
# A pull request and the issues it closes: which issues those are, which
# milestone they put it in, and the summary left on it once QA has accepted
# them all.
#
# A pull request usually closes the one issue its feature started from, but a
# person can link more — a `Closes #N` added to the body, or the issue's
# Development box. Everything that asks "what does this PR stand for" asks here,
# so the milestone and the QA hand-off cannot disagree about the set.
#
# The summary is for whoever merges. They should not need to open the issue to
# decide: the preview to look at, QA's verdict, the acceptance criteria, what
# the review found and whether it actually ran on this head, the checks, the
# regressions. All of it is read from GitHub and the feature's state — nothing
# here needs a Claude session.
#
#   pr_handoff.py tickets    <cwd> <pr> [issue]
#       The PR's issues, one number per line: closing references first, the
#       feature's own issue added when GitHub has not linked it.
#   pr_handoff.py milestones <cwd> <pr> [issue]
#       `<title>\t<#a, #b>` per distinct milestone of those issues. An issue
#       with no milestone is not a candidate: it does not disagree with anyone.
#   pr_handoff.py summary    <cwd> <pr> <state.json> <done column> <issue>...
#       The comment's text, marker first.
#   pr_handoff.py comment    <cwd> <pr> <file>
#       Writes the file as the PR's summary comment: edits ours if there is
#       one, posts otherwise. Prints `posted`, `edited` or `failed`.
#
# Silent on trouble, like pr_context.py: whatever cannot be read is left out or
# said to be unknown, and a summary with a gap is still worth posting.
import datetime
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acceptance  # noqa: E402
import issue_comments  # noqa: E402
from pr_context import FINDINGS_CHECK, GREEN, gh, gh_json  # noqa: E402


def repo_of(cwd):
    view = gh_json(["repo", "view", "--json", "nameWithOwner"], cwd=cwd)
    return (view or {}).get("nameWithOwner") or ""


def tickets(cwd, pr, issue=""):
    """The issues this PR closes, as ints, in a stable order."""
    view = gh_json(["pr", "view", str(pr), "--json", "closingIssuesReferences"], cwd=cwd)
    found = []
    for ref in (view or {}).get("closingIssuesReferences") or []:
        number = ref.get("number")
        if isinstance(number, int) and number not in found:
            found.append(number)
    if str(issue).isdigit() and int(issue) not in found:
        found.append(int(issue))
    return found


def milestones(cwd, numbers):
    """{milestone title: [issue numbers]}, in the order first seen."""
    repo = repo_of(cwd)
    if not repo:
        return {}
    out = {}
    for number in numbers:
        data = gh_json(["api", "repos/%s/issues/%s" % (repo, number)], cwd=cwd)
        title = (((data or {}).get("milestone") or {}).get("title") or "").strip()
        if title:
            out.setdefault(title, []).append(number)
    return out


# --- the summary -------------------------------------------------------------

THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { isResolved }
      }
    }
  }
}
"""


def threads(cwd, pr, repo):
    """(all review threads, still open), or None when unreadable."""
    owner, name = repo.split("/", 1)
    total = unresolved = 0
    after = None
    while True:
        args = ["api", "graphql", "-f", "query=%s" % THREADS_QUERY,
                "-F", "owner=%s" % owner, "-F", "name=%s" % name,
                "-F", "number=%s" % pr]
        if after:
            args += ["-f", "after=%s" % after]
        data = gh_json(args, cwd=cwd)
        try:
            page = data["data"]["repository"]["pullRequest"]["reviewThreads"]
        except (TypeError, KeyError):
            return None
        for t in page.get("nodes") or []:
            total += 1
            if not t.get("isResolved"):
                unresolved += 1
        info = page.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return total, unresolved
        after = info.get("endCursor")


def review_line(cwd, repo, head):
    """Whether the automatic review finished on this head, in words.

    The question is the one the summary exists to answer: zero findings means
    nothing only if the review looked. The findings check carries
    `external_id: reviewed` only after a review that really ran (see
    pr_context.review_state), so a green check without it is a review that
    skipped or failed before reading anything.
    """
    from urllib.parse import quote
    runs = gh_json(["api", "repos/%s/commits/%s/check-runs?check_name=%s"
                    % (repo, head, quote(FINDINGS_CHECK, safe=""))], cwd=cwd)
    if runs is None:
        return "unknown — the checks could not be read"
    found = [r for r in (runs.get("check_runs") or []) if r.get("name") == FINDINGS_CHECK]
    if not found:
        return "⚠ no review result on this head — zero findings may mean it never looked"
    latest = found[0]
    if (latest.get("status") or "") != "completed":
        return "⚠ still running on this head"
    if (latest.get("external_id") or "") != "reviewed":
        return "⚠ did not finish on this head (failed or skipped) — zero findings may mean it never looked"
    if (latest.get("conclusion") or "") != "success":
        return "⚠ finished on this head with findings still open"
    return "✓ finished on this head, nothing left open"


def checks_line(rollup):
    if not rollup:
        return "none reported"
    red, running = [], []
    for c in rollup:
        name = c.get("name") or c.get("context") or "?"
        status = (c.get("status") or "").upper()
        state = (c.get("conclusion") or c.get("state") or "").upper()
        if (status and status != "COMPLETED") or state in ("PENDING", "EXPECTED", ""):
            running.append(name)
        elif state not in GREEN:
            red.append(name)
    parts = []
    # Once each: the findings verdict comes as a check run and a status.
    if red:
        parts.append("⚠ red: " + ", ".join(dict.fromkeys(red)))
    if running:
        parts.append("still running: " + ", ".join(dict.fromkeys(running)))
    return "; ".join(parts) if parts else "✓ all %d green" % len(rollup)


def regression_line(state):
    words = {"passed": "✓ passed", "failed": "⚠ failed"}
    regression = state.get("regression") or {}
    parts = []
    for stage in ("local", "preview"):
        status = (regression.get(stage) or {}).get("status")
        parts.append("%s %s" % (stage, words.get(status, "not run")))
    return " · ".join(parts)


def acceptance_line(cwd, number):
    rows = acceptance.parse(acceptance.fetch_text(number, cwd))
    if not rows:
        return "#%s: none recorded" % number
    ticked = sum(1 for _, _, done in rows if done)
    line = "#%s: %d of %d ticked" % (number, ticked, len(rows))
    if ticked < len(rows):
        line = "⚠ " + line + " — not ticked: " + ", ".join(
            cid for cid, _, done in rows if not done)
    else:
        line = "✓ " + line
    return line


def summary(cwd, pr, state_path, done, numbers):
    try:
        with open(state_path) as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        state = {}
    repo = repo_of(cwd)
    view = gh_json(["pr", "view", str(pr), "--json",
                    "headRefOid,statusCheckRollup"], cwd=cwd) or {}
    head = view.get("headRefOid") or ""

    rows = []
    preview = ((state.get("regression") or {}).get("preview") or {}).get("url")
    rows.append(("Preview", preview or "unknown"))
    rows.append(("QA", ", ".join("#%s %s" % (n, done) for n in numbers)))
    returns = state.get("qa_returns") or 0
    rows.append(("Returned to development", "%d time%s" % (returns, "" if returns == 1 else "s")))
    rows.append(("Acceptance criteria", "<br>".join(acceptance_line(cwd, n) for n in numbers)))
    counted = threads(cwd, pr, repo) if repo else None
    if counted is None:
        rows.append(("Review findings", "unknown"))
    else:
        total, unresolved = counted
        rows.append(("Review findings", "%s%d found, %d resolved, %d open"
                     % ("⚠ " if unresolved else "", total, total - unresolved, unresolved)))
    rows.append(("Last review", review_line(cwd, repo, head) if repo and head else "unknown"))
    rows.append(("Checks", checks_line(view.get("statusCheckRollup") or [])))
    rows.append(("Regression", regression_line(state)))

    when = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        issue_comments.MERGE_READY,
        "## Ready to merge",
        "",
        "QA accepted every issue this pull request closes. Everything needed for "
        "the merge decision is below; a ⚠ is worth a look first.",
        "",
        "| | |",
        "|---|---|",
    ]
    lines += ["| %s | %s |" % (k, v.replace("|", "\\|")) for k, v in rows]
    lines += ["", "<sub>Head %s · written by sclaude at %s</sub>" % (head[:7] or "?", when)]
    return "\n".join(lines) + "\n"


def comment(cwd, pr, path):
    """Post the summary, or rewrite ours in place."""
    with open(path) as fh:
        body = fh.read()
    repo = repo_of(cwd)
    if not repo:
        return "failed"
    out = gh(["api", "--paginate", "repos/%s/issues/%s/comments" % (repo, pr),
              "--jq", ".[] | select(.body | contains(\"%s\")) | .id"
              % issue_comments.MERGE_READY], cwd=cwd)
    ours = (out or "").split()
    if ours:
        return "edited" if issue_comments.edit(ours[0], body, cwd) else "failed"
    try:
        done = subprocess.run(
            ["gh", "api", "repos/%s/issues/%s/comments" % (repo, pr), "--input", "-"],
            input=json.dumps({"body": body}), cwd=cwd, capture_output=True,
            text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return "failed"
    return "posted" if done.returncode == 0 else "failed"


def main():
    argv = sys.argv[1:]
    if len(argv) < 3:
        return 0
    mode, cwd, pr = argv[0], argv[1], argv[2]
    try:
        if mode == "tickets":
            for n in tickets(cwd, pr, argv[3] if len(argv) > 3 else ""):
                print(n)
        elif mode == "milestones":
            found = milestones(cwd, tickets(cwd, pr, argv[3] if len(argv) > 3 else ""))
            for title, numbers in found.items():
                print("%s\t%s" % (title, ", ".join("#%s" % n for n in numbers)))
        elif mode == "summary" and len(argv) >= 6:
            sys.stdout.write(summary(cwd, pr, argv[3], argv[4], argv[5:]))
        elif mode == "comment" and len(argv) >= 4:
            print(comment(cwd, pr, argv[3]))
    except Exception:
        if mode == "comment":
            print("failed")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
