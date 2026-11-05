#!/usr/bin/env python3
#
# Where issues stand on GitHub, for the terminal's issue picker (pick_start in
# picker.sh, through `issue_list.py rows`): drawn in yellow, rightmost, after
# the labels.
#
#   board_status.py <owner/repo> <number>...
#       one line "<number>\t<status>" per issue that has one
#
# The status is the issue's "Status" column on its project board — the first
# board that gives one, as issue_status_now in board.sh reads it. An issue on
# no board, or with an empty column there, shows "Closed" when it is closed and
# nothing otherwise.
#
# One GraphQL request for all the issues, an alias per number: a request per
# issue would be felt every time the picker opens.
#
# Silent on any trouble — no gh, no network, no project scope: empty output and
# exit code 0, so the picker draws as it did before this column existed.
import json
import subprocess
import sys


def query(numbers):
    """The GraphQL query that reads every number at once."""
    parts = []
    for n in numbers:
        parts.append(
            "i%d: issueOrPullRequest(number:%d) {"
            " ... on Issue { state projectItems(first:10) { ...items } }"
            " ... on PullRequest { state projectItems(first:10) { ...items } }"
            " }" % (n, n))
    return ("query($owner:String!, $name:String!) {"
            " repository(owner:$owner, name:$name) { %s } }"
            " fragment items on ProjectV2ItemConnection { nodes {"
            " fieldValueByName(name:\"Status\") {"
            " ... on ProjectV2ItemFieldSingleSelectValue { name } } } }"
            % " ".join(parts))


def status_of(node):
    """One issue's node from the answer -> its status, or ""."""
    if not isinstance(node, dict):
        return ""
    for item in (node.get("projectItems") or {}).get("nodes") or []:
        name = ((item or {}).get("fieldValueByName") or {}).get("name") or ""
        if name.strip():
            return " ".join(name.split())
    if (node.get("state") or "").upper() in ("CLOSED", "MERGED"):
        return "Closed"
    return ""


def statuses(repo, numbers):
    """{number: status} of the issues that have one; {} when gh cannot say."""
    if "/" not in repo:
        return {}
    owner, name = repo.split("/", 1)
    numbers = sorted({int(n) for n in numbers if str(n).isdigit()})
    if not numbers:
        return {}
    try:
        done = subprocess.run(
            ["gh", "api", "graphql", "-f", "owner=" + owner,
             "-f", "name=" + name, "-f", "query=" + query(numbers)],
            capture_output=True, text=True, timeout=30)
        data = json.loads(done.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    # gh exits non-zero when one alias fails (an issue deleted, a number that
    # is neither), yet the rest of the answer is still good: read what came.
    repo_data = (data.get("data") or {}).get("repository") or {}
    found = {}
    for n in numbers:
        status = status_of(repo_data.get("i%d" % n))
        if status:
            found[n] = status
    return found


def main(argv):
    if len(argv) < 1 or "/" not in argv[0]:
        print("usage: board_status.py <owner/repo> <number>...", file=sys.stderr)
        return 2
    for n, status in sorted(statuses(argv[0], argv[1:]).items()):
        print("%d\t%s" % (n, status))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
