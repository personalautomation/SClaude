#!/usr/bin/env python3
"""What `demo_refresh` in deploy.sh reads from a feature's demo history
after the session that records the demo again: the recordings it made are
the ones past the count taken before it.

    demo_refresh.py count <wt>                     recordings in the history
    demo_refresh.py held <wt> <before>             the ids to publish, in order:
                                                   the last delta, the last full
                                                   (last_tries); nothing when the
                                                   session ended on keep
    demo_refresh.py findings <wt> <file> <before>  what the session found wrong,
                                                   and the checks that failed in
                                                   last_tries, kept or not
    demo_refresh.py kept <wt> <before>             why nothing was recorded, if
                                                   the session kept the demo

The history is `history.json` in DEMO_DIR (skills/sdemo/demo.py)."""
import json
import os
import sys

DEMO_DIR = os.path.join(".sclaude", "local", "demo")


def history(wt):
    try:
        with open(os.path.join(wt, DEMO_DIR, "history.json")) as fh:
            found = json.load(fh)
        return found if isinstance(found, list) else []
    except (OSError, ValueError):
        return []


def since(wt, before):
    return history(wt)[int(before):]


def last_tries(wt, before):
    """The last delta, then the last full demo, the session recorded and
    that played; a kept entry is no recording."""
    played = [e for e in since(wt, before) if not e.get("broken") and not e.get("kept")]
    out = []
    for kind in ("delta", "main"):
        last = [e for e in played if e.get("kind") == kind]
        if last:
            out.append(last[-1]["id"])
    return out


def held(wt, before):
    """What to publish: the session's last tries, unless it ended on
    `demo.py keep` — it decided they show nothing new, and none goes out."""
    new = since(wt, before)
    if new and new[-1].get("kept"):
        return []
    return last_tries(wt, before)


def findings(wt, file, before):
    """The session's own lines, then the checks that failed in its last
    delta and its last full recording — published or, after `keep`, not: a
    check is a finding, not a recording that did not play, and a fault
    seen in a try is no less one for the try staying held."""
    out = []
    try:
        with open(file) as fh:
            out += [line.strip().lstrip("-* ").strip() for line in fh if line.strip()]
    except OSError:
        pass
    for demo in last_tries(wt, before):
        try:
            with open(os.path.join(wt, DEMO_DIR, demo, "demo.json")) as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            rec = {}
        for sc in rec.get("scenarios") or []:
            for st in sc.get("steps") or []:
                if st.get("ok") is False:
                    out.append("%s: a check failed — %s (%s)" % (
                        sc.get("title") or "?", st.get("text") or "?", st.get("error") or "not seen"))
    return [line for line in out if line]


def kept(wt, before):
    new = since(wt, before)
    if new and new[-1].get("kept"):
        return "the demo %s still shows the feature — %s" % (new[-1]["id"], new[-1]["kept"])
    return ""


def main(argv):
    if len(argv) < 3:
        sys.exit("usage: demo_refresh.py count|held|findings|kept <wt> …")
    cmd, wt = argv[1], argv[2]
    if cmd == "count":
        print(len(history(wt)))
    elif cmd == "held":
        print("\n".join(held(wt, argv[3])))
    elif cmd == "findings":
        print("\n".join(findings(wt, argv[3], argv[4])))
    elif cmd == "kept":
        print(kept(wt, argv[3]))
    else:
        sys.exit("demo_refresh.py: no command %s" % cmd)


if __name__ == "__main__":
    main(sys.argv)
