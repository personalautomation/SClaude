#!/usr/bin/env python3
#
# What Claude spent on a product, read from Claude Code's own transcripts.
#
# Every session Claude Code runs leaves a JSON Lines transcript under
# ~/.claude/projects/<the working directory, every non-alphanumeric made a
# dash>/<session>.jsonl, and the subagents it started beside it, under
# <session>/subagents/. A product's sessions are the ones run in its main
# checkout or in one of its worktrees, `<repo>-<feature>` (worktree.sh), so
# the directory's name says which feature a session worked on.
#
# What is read from each:
#
#   cost-state     Claude Code's own running account of the process: dollars,
#                  tokens by kind and model, lines it wrote, time in the API and
#                  in tools. Cumulative, so the last one of each run counts.
#                  Used as it is — a price worked out here would be a guess.
#   custom-title   the name sclaude gives a step's session (`2-code 💻/<feature>`,
#                  or `<feature>/code` before the icons) — the step it ran
#   assistant      each tool call, and the token usage of a transcript that has
#                  no cost-state (an older Claude Code)
#   user           the messages a person typed (promptSource "typed", or a
#                  plain text line from an older Claude Code) — the first of a
#                  session sclaude started is sclaude's own prompt
#   the person     each time they had to step in — a typed message after
#                  Claude's turn, an answer to Claude's question — with how
#                  long it took them (from Claude's last line, capped at AWAY)
#                  and how many tool calls Claude made since the time before:
#                  [[when, seconds, calls]]
#   the rest       tool calls refused (toolDenialKind), context compactions,
#                  API errors
#
# A transcript is 1–100 MB, and a product has hundreds. Each file's summary is
# kept beside the page with the size and mtime it was read at, so a refresh
# reads only the sessions that grew since.
import glob
import json
import os
import re
from datetime import datetime

ROOT = os.path.expanduser("~/.claude/projects")

# A step's session name: `<cycle number>-<step>[(n)] [icon]/<feature>` now,
# `<feature>/<step>` before. The fixing and friction sessions carry their
# stage or count in the name; they are folded into one word each.
TITLE_STEP = re.compile(r"^\d+-(?:\d+-)?([a-z]+(?:-[a-z]+)*)(?:-\d+)?(?:\(\d+\))?(?:\s|$)")
STEP_WORDS = {"plan", "code", "pr", "review", "fix", "friction", "epilogue", "retro",
              "sync", "deferred", "regression", "status"}

TIMESTAMP = re.compile(rb'"timestamp":"([^"]+)"')

# Bumped when a summary gains a field: every transcript is read again once.
VERSION = 5

# A person who takes longer than this to answer was away rather than working:
# their time counts up to here and no further.
AWAY = 30 * 60


def project_name(path):
    """The directory Claude Code keeps a working directory's sessions in."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def step_of(title):
    """The cycle's step a session ran, from the name sclaude gave it."""
    if not title:
        return "manual"
    # The feature's own name starts with a number too (`12-review-the-
    # menu`), so a part counts only when what follows the number is a step.
    for part in title.split("/"):
        m = TITLE_STEP.match(part.strip())
        if m and (fold(m.group(1)) in STEP_WORDS):
            return fold(m.group(1))
    # Older names: `<feature>/<step>`, or `<step>/<feature>` for the
    # sessions sclaude started outside the four steps.
    for part in title.split("/"):
        word = fold((part.strip().split(" ") or [""])[0])
        if word in STEP_WORDS:
            return word
    return "other"


def fold(word):
    """fix-local, fix-preview and fix-prod are one step: fixing; the friction
    review after any of them is a friction review."""
    if word.endswith("-friction"):
        return "friction"
    return "fix" if re.fullmatch(r"fix(-[a-z]+)?", word) else word


def wait(start, end):
    """Seconds from one ISO time to another, capped at AWAY; 0 when unknown."""
    try:
        a = datetime.fromisoformat(start.replace("Z", "+00:00"))
        b = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return 0
    return max(0, min(AWAY, int((b - a).total_seconds())))


def typed(entry):
    """A message a person typed — or, for the first one, sclaude did."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isCompactSummary"):
        return False
    if entry.get("promptSource"):
        return entry["promptSource"] == "typed"
    content = (entry.get("message") or {}).get("content")
    return isinstance(content, str) and not content.startswith("<")


def read(path):
    """One transcript's summary, or None when it cannot be read."""
    usage, tools, seen_tools = {}, {}, set()
    runs, denials = {}, {}
    title, first, last, continued = None, None, None, None
    compactions = errors = prompts = questions = 0
    # The person's turns: [[when, seconds they took, Claude's calls since]].
    human, pending_asks, since_last, last_claude = [], {}, 0, None
    try:
        fh = open(path, "rb")
    except OSError:
        return None
    with fh:
        for line in fh:
            at = line.rfind(b'"timestamp":"')
            if at >= 0:
                m = TIMESTAMP.match(line, at)
                if m:
                    stamp = m.group(1).decode("ascii", "replace")
                    first = first or stamp
                    last = stamp
            if b'"type":"assistant"' in line:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                msg = entry.get("message") or {}
                if entry.get("isApiErrorMessage"):
                    errors += 1
                if isinstance(msg.get("usage"), dict) and msg.get("id"):
                    usage[msg["id"]] = (msg.get("model"), msg["usage"])
                last_claude = entry.get("timestamp") or last_claude
                for block in msg.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use" \
                            and block.get("id") not in seen_tools:
                        seen_tools.add(block.get("id"))
                        name = block.get("name") or "?"
                        tools[name] = tools.get(name, 0) + 1
                        since_last += 1
                        # One call can carry up to four questions; each is a
                        # thing the person had to decide.
                        if name == "AskUserQuestion":
                            asked = (block.get("input") or {}).get("questions")
                            questions += len(asked) if isinstance(asked, list) and asked else 1
                            pending_asks[block.get("id")] = entry.get("timestamp")
                continue
            if b'"cost-state"' in line:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get("type") == "cost-state":
                    runs[str(entry.get("startTime"))] = entry
                continue
            if b'"continued-in"' in line:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get("type") == "continued-in":
                    continued = entry.get("continuedInSessionId") or continued
                continue
            if b'"custom-title"' in line:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get("type") == "custom-title" and entry.get("customTitle"):
                    title = entry["customTitle"]
                continue
            if b'"type":"user"' in line and b'"tool_result"' not in line:
                try:
                    entry = json.loads(line)
                except ValueError:
                    entry = {}
                if typed(entry):
                    prompts += 1
                    # The session's opening prompt follows no turn of Claude's.
                    if last_claude:
                        human.append([entry.get("timestamp"),
                                      wait(last_claude, entry.get("timestamp")), since_last])
                        since_last = 0
            elif pending_asks and b'"tool_result"' in line and \
                    any(i and i.encode() in line for i in pending_asks):
                try:
                    entry = json.loads(line)
                except ValueError:
                    entry = {}
                for block in (entry.get("message") or {}).get("content") or []:
                    asked_at = pending_asks.pop((block or {}).get("tool_use_id"), None) \
                        if isinstance(block, dict) else None
                    if asked_at:
                        human.append([entry.get("timestamp"), wait(asked_at, entry.get("timestamp")),
                                      since_last])
                        since_last = 0
            if b'"toolDenialKind"' in line:
                try:
                    kind = json.loads(line).get("toolDenialKind")
                except ValueError:
                    kind = None
                if kind:
                    denials[kind] = denials.get(kind, 0) + 1
            if b'"isCompactSummary":true' in line:
                compactions += 1

    tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "thinking": 0}
    cost, models, lines_added, lines_removed, api_ms, tool_ms = None, {}, 0, 0, 0, 0
    if runs:
        cost = 0.0
        for run in runs.values():
            cost += float(run.get("totalCostUSD") or 0)
            lines_added += int(run.get("totalLinesAdded") or 0)
            lines_removed += int(run.get("totalLinesRemoved") or 0)
            api_ms += int(run.get("totalAPIDuration") or 0)
            tool_ms += int(run.get("totalToolDuration") or 0)
            for model, u in (run.get("modelUsage") or {}).items():
                tokens["input"] += int(u.get("inputTokens") or 0)
                tokens["output"] += int(u.get("outputTokens") or 0)
                tokens["cache_read"] += int(u.get("cacheReadInputTokens") or 0)
                tokens["cache_write"] += int(u.get("cacheCreationInputTokens") or 0)
                tokens["thinking"] += int(u.get("thinkingTokens") or 0)
                models[model] = models.get(model, 0) + float(u.get("costUSD") or 0)
    else:
        # No account of its own: the messages' usage, summed. A subagent's
        # transcript is always this case, and its cost is already in the
        # account of the session that started it.
        for model, u in usage.values():
            tokens["input"] += int(u.get("input_tokens") or 0)
            tokens["output"] += int(u.get("output_tokens") or 0)
            tokens["cache_read"] += int(u.get("cache_read_input_tokens") or 0)
            tokens["cache_write"] += int(u.get("cache_creation_input_tokens") or 0)
            tokens["thinking"] += int((u.get("output_tokens_details") or {}).get("thinking_tokens") or 0)
    return {"title": title, "start": first, "end": last, "cost": cost, "models": models,
            "tokens": tokens, "tools": tools, "denials": denials,
            "compactions": compactions, "api_errors": errors, "prompts": prompts,
            "questions": questions, "human": human,
            "lines_added": lines_added, "lines_removed": lines_removed,
            "api_ms": api_ms, "tool_ms": tool_ms, "continued_in": continued}


def sessions(repo, cache_path, root=None):
    """[summary + project, feature, session, sub, step] of every transcript
    of the product, each read again only when it changed since the cache."""
    root = root or ROOT
    base = project_name(os.path.realpath(repo))
    try:
        with open(cache_path, encoding="utf-8") as fh:
            cache = json.load(fh)
    except (OSError, ValueError):
        cache = {}
    out, fresh = [], {}
    dirs = [d for d in glob.glob(os.path.join(glob.escape(root), glob.escape(base) + "*"))
            if os.path.isdir(d)]
    for d in dirs:
        name = os.path.basename(d)
        if name != base and not name.startswith(base + "-"):
            continue
        rest = name[len(base) + 1:]
        # sclaude's workshop, .sclaude/local/instruments in a tree: work on
        # the orchestrator, done from this product.
        workshop = "sclaude-local-instruments" in rest
        feature = rest.split("-sclaude-local-instruments", 1)[0].rstrip("-") or "main"
        files = glob.glob(os.path.join(glob.escape(d), "*.jsonl")) + \
            glob.glob(os.path.join(glob.escape(d), "*", "subagents", "*.jsonl"))
        # Claude Code may carry a conversation on under a new id, in a new
        # transcript that holds all of it, its cost account included (`chain`
        # in session_end.py). The old one is then left out, and its subagents
        # go to the session it became; the old one counted beside it was the
        # same conversation twice.
        mains, became = [], {}
        for path in files:
            rel = os.path.relpath(path, root)
            try:
                st = os.stat(path)
            except OSError:
                continue
            key = [VERSION, st.st_size, int(st.st_mtime)]
            kept = cache.get(rel)
            if kept and kept.get("key") == key:
                summary = kept["summary"]
            else:
                summary = read(path)
                if summary is None:
                    continue
            fresh[rel] = {"key": key, "summary": summary}
            sub = os.sep + "subagents" + os.sep in rel
            parent = os.path.basename(os.path.dirname(os.path.dirname(path))) if sub \
                else os.path.basename(path)[:-len(".jsonl")]
            item = dict(summary)
            item.update(project=name, feature=feature, session=parent, sub=sub,
                        workshop=workshop,
                        step="workshop" if workshop else step_of(summary.get("title")))
            mains.append(item)
            nxt = summary.get("continued_in")
            if not sub and nxt and os.path.exists(os.path.join(d, nxt + ".jsonl")):
                became[parent] = nxt
        for item in mains:
            if not item["sub"] and item["session"] in became:
                continue
            seen = set()
            while item["session"] in became and item["session"] not in seen:
                seen.add(item["session"])
                item["session"] = became[item["session"]]
            out.append(item)
    try:
        tmp = cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(fresh, fh)
        os.replace(tmp, cache_path)
    except OSError:
        pass
    return out
