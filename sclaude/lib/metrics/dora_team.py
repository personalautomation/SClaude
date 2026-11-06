# The DORA page's team section: the profiles, simulated or real, and the
# section drawn from them.
#
# Part of sclaude/lib/metrics/dora.py.

import json
import os

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import page_asset  # noqa: E402
import metrics_guide  # noqa: E402

import dora_numbers, dora_page




# The team part's script: draws the simulated teammates from the base, keeps
# the draw in the browser, and lays the developers side by side.
TEAM_JS = page_asset.read(__file__, "dora_team.js")


# The teammates the team part simulates, and how each differs from the one real
# developer: [mode, low, high] per figure — "x" multiplies the real figure by a
# draw between low and high, "abs" draws the figure itself, "none" has none.
# Alex and Anastasia write far more code than the base, Anastasia cleaner;
# Kris only fixes bugs.
SIMULATED = ("Alex", "Anastasia", "Kris")
PROFILES = {
    "features": {"Alex": ["x", 1.6, 2.2], "Anastasia": ["x", 1.4, 2.0], "Kris": ["abs", 0, 0]},
    "prs": {"Alex": ["x", 1.8, 2.6], "Anastasia": ["x", 1.5, 2.2], "Kris": ["x", 0.8, 1.4]},
    "commits": {"Alex": ["x", 2.0, 3.0], "Anastasia": ["x", 1.8, 2.6], "Kris": ["x", 0.6, 1.0]},
    "lines": {"Alex": ["x", 2.5, 4.0], "Anastasia": ["x", 2.0, 3.5], "Kris": ["x", 0.1, 0.25]},
    "bugs": {"Alex": ["x", 0.5, 0.9], "Anastasia": ["x", 0.4, 0.8], "Kris": ["x", 1.2, 1.8]},
    "cycle": {"Alex": ["x", 0.9, 1.3], "Anastasia": ["x", 0.8, 1.1], "Kris": ["none", 0, 0]},
    "lead": {"Alex": ["x", 1.0, 1.4], "Anastasia": ["x", 0.8, 1.1], "Kris": ["x", 0.3, 0.6]},
    "aging": {"Alex": ["x", 1.1, 1.5], "Anastasia": ["x", 0.8, 1.1], "Kris": ["x", 0.3, 0.6]},
    "pr_size": {"Alex": ["x", 1.8, 2.8], "Anastasia": ["x", 1.3, 2.0], "Kris": ["x", 0.1, 0.25]},
    "green": {"Alex": ["x", 0.8, 1.0], "Anastasia": ["x", 1.05, 1.3], "Kris": ["x", 0.9, 1.2]},
    "rounds": {"Alex": ["x", 1.2, 1.6], "Anastasia": ["x", 0.6, 0.9], "Kris": ["abs", 1, 3]},
    "threads": {"Alex": ["x", 1.3, 1.8], "Anastasia": ["x", 0.7, 1.0], "Kris": ["abs", 2, 8]},
    "escaped": {"Alex": ["abs", 0.05, 0.15], "Anastasia": ["abs", 0, 0.05], "Kris": ["abs", 0, 0.03]},
    "reopened": {"Alex": ["x", 1.0, 1.5], "Anastasia": ["x", 0.5, 0.9], "Kris": ["x", 0.6, 1.2]},
    "run": {"Alex": ["x", 0.8, 1.2], "Anastasia": ["x", 1.2, 1.6], "Kris": ["x", 0.6, 0.9]},
    "person_share": {"Alex": ["x", 0.8, 1.1], "Anastasia": ["x", 0.7, 0.95], "Kris": ["x", 1.1, 1.4]},
    "interventions": {"Alex": ["x", 1.1, 1.5], "Anastasia": ["x", 0.7, 1.0], "Kris": ["none", 0, 0]},
    "questions": {"Alex": ["x", 0.8, 1.2], "Anastasia": ["x", 0.6, 0.9], "Kris": ["none", 0, 0]},
    "sessions": {"Alex": ["x", 1.8, 2.6], "Anastasia": ["x", 1.6, 2.2], "Kris": ["x", 0.8, 1.2]},
    "person_hours": {"Alex": ["x", 1.6, 2.4], "Anastasia": ["x", 1.2, 1.8], "Kris": ["x", 0.8, 1.2]},
    "spend": {"Alex": ["x", 2.0, 3.0], "Anastasia": ["x", 1.6, 2.4], "Kris": ["x", 0.4, 0.7]},
    "spend_feature": {"Alex": ["x", 1.0, 1.4], "Anastasia": ["x", 0.8, 1.1], "Kris": ["none", 0, 0]},
    # Working with Claude. Alex uses it heavily and loosely; Anastasia is the
    # practised one; Kris is still taking it up.
    "ai_commits": {"Alex": ["x", 0.9, 1.05], "Anastasia": ["x", 0.95, 1.1], "Kris": ["x", 0.3, 0.5]},
    "sessions_week": {"Alex": ["x", 1.8, 2.6], "Anastasia": ["x", 1.6, 2.2], "Kris": ["x", 0.4, 0.7]},
    "tokens_week": {"Alex": ["x", 2.2, 3.2], "Anastasia": ["x", 1.4, 2.0], "Kris": ["x", 0.2, 0.4]},
    "subagents": {"Alex": ["x", 1.2, 1.8], "Anastasia": ["x", 1.5, 2.2], "Kris": ["x", 0.2, 0.5]},
    "skills": {"Alex": ["x", 0.5, 0.9], "Anastasia": ["x", 1.3, 2.0], "Kris": ["x", 0.3, 0.6]},
    "plan": {"Alex": ["x", 0.3, 0.7], "Anastasia": ["x", 1.5, 2.5], "Kris": ["abs", 0, 0.03]},
    "mcp": {"Alex": ["x", 0.8, 1.3], "Anastasia": ["x", 1.4, 2.2], "Kris": ["x", 0.5, 1.0]},
    "top_model": {"Alex": ["abs", 0.92, 0.99], "Anastasia": ["abs", 0.55, 0.75], "Kris": ["abs", 0.8, 0.95]},
    "cache": {"Alex": ["x", 0.85, 0.95], "Anastasia": ["x", 1.0, 1.03], "Kris": ["x", 0.75, 0.9]},
    "unattended": {"Alex": ["x", 0.8, 1.0], "Anastasia": ["x", 1.1, 1.3], "Kris": ["x", 0.5, 0.8]},
    "minutes_hour": {"Alex": ["x", 0.9, 1.2], "Anastasia": ["x", 0.6, 0.85], "Kris": ["x", 1.3, 1.8]},
    "rejected": {"Alex": ["x", 1.5, 2.5], "Anastasia": ["x", 0.4, 0.8], "Kris": ["x", 0.8, 1.2]},
    "refusals": {"Alex": ["x", 1.2, 1.8], "Anastasia": ["x", 0.6, 0.9], "Kris": ["x", 0.9, 1.4]},
    "compactions": {"Alex": ["x", 1.5, 2.5], "Anastasia": ["x", 0.6, 1.0], "Kris": ["x", 0.3, 0.7]},
    "thinking": {"Alex": ["x", 0.8, 1.0], "Anastasia": ["x", 1.0, 1.2], "Kris": ["x", 0.9, 1.1]},
    "kloc": {"Alex": ["x", 0.7, 1.0], "Anastasia": ["x", 0.6, 0.9], "Kris": ["x", 1.5, 2.5]},
    "mix_feat": {"Alex": ["x", 1.3, 1.6], "Anastasia": ["x", 1.2, 1.5], "Kris": ["abs", 0, 0.03]},
    "mix_fix": {"Alex": ["x", 0.6, 0.9], "Anastasia": ["x", 0.6, 0.9], "Kris": ["abs", 0.8, 0.9]},
    "mix_refactor": {"Alex": ["x", 0.8, 1.5], "Anastasia": ["x", 1.5, 2.5], "Kris": ["abs", 0.02, 0.06]},
    "mix_other": {"Alex": ["x", 0.8, 1.2], "Anastasia": ["x", 0.8, 1.2], "Kris": ["abs", 0.05, 0.1]},
}


def team_mode(repo):
    """`metricsTeam` for this machine: its own .sclaude/local/config.json
    first — outside git, so turning the demo on for one laptop does not turn
    it on for the team — then the product's committed config, read as
    `sclaude config` reads them (overrides in config_menu.py)."""
    import config_menu
    config = os.path.join(repo, ".sclaude", "config.json")
    found = config_menu.overrides(config).get("metricsTeam") \
        or (config_menu.load(config) or {}).get("metricsTeam")
    return found if found in ("real", "demo") else "real"


def team_section(x, cur, dv, sw, hm, ai, first_time, hist):
    """Developers side by side, for `metricsTeam: demo`: the real developer's
    figures are the product's — on one developer's product they are the same
    thing — and the generated teammates are drawn from them in the browser
    (TEAM_JS) by PROFILES, the draw kept per browser."""
    authors = sorted((hist.get("authors") or {}).items(), key=lambda kv: -kv[1]["commits"])
    me = authors[0][0] if authors else "You"
    types = dict(sw["types"])
    changes = sum(types.values()) or 1
    uses = dict(ai["uses"])
    spend_by_model = x["models"] or {}
    top_model = dora_numbers.ratio(sum(v for k, v in spend_by_model.items() if "opus" in k.lower()),
                      sum(spend_by_model.values()))

    def kind(*names):
        return sum(types.get(n, 0) for n in names) / changes
    rows = [
        ("features", "Features finished", "Output", "int", x["done"], None),
        ("prs", "Pull requests merged", "Output", "int", x["merged"], None),
        ("commits", "Commits", "Output", "int", hist.get("commits"), None),
        ("lines", "Lines changed", "Output", "int", (hist.get("added") or 0) + (hist.get("removed") or 0), None),
        ("bugs", "Bugs fixed", "Output", "int", types.get("fix", 0), None),
        ("cycle", "Feature cycle time", "Speed", "span", x["cycle"], None),
        ("lead", "Lead time for changes", "Speed", "span", cur["lead"], None),
        ("aging", "PR aging", "Speed", "span", dv["aging"], None),
        ("pr_size", "Pull request size", "Speed", "int", x["pr_size"], None),
        ("green", "Regression green first time", "Quality", "share", first_time, 1.0),
        ("rounds", "Review rounds per feature", "Quality", "dec1", x["rounds_per_feature"], None),
        ("threads", "Review threads per feature", "Quality", "int", x["threads_per_feature"], None),
        ("escaped", "Escaped defects", "Quality", "share", sw["escaped"], 1.0),
        ("reopened", "Reopened issues", "Quality", "share", sw["reopened"], 1.0),
        ("ai_commits", "Commits written by Claude", "AI adoption", "share",
         dora_numbers.ratio(hist.get("by_claude"), hist.get("commits")), 1.0),
        ("sessions", "Sessions, last 30 days", "AI adoption", "int", x["sessions_recent"], None),
        ("sessions_week", "Sessions per week", "AI adoption", "dec1", ai["sessions_per_week"], None),
        ("tokens_week", "Tokens per week", "AI adoption", "int", ai["tokens_per_week"], None),
        ("person_hours", "Person's hours with Claude", "AI adoption", "dec1", hm["person_s"] / 3600, None),
        ("subagents", "Subagent use", "AI adoption", "share", uses.get("Subagents"), 1.0),
        ("skills", "Skill use", "AI adoption", "share", uses.get("Skills"), 1.0),
        ("plan", "Plan mode use", "AI adoption", "share", uses.get("Plan mode"), 1.0),
        ("mcp", "MCP tool use", "AI adoption", "share", uses.get("MCP tools"), 1.0),
        ("top_model", "Top-model share of spend", "AI adoption", "share", top_model, 1.0),
        ("cache", "Cache hit rate", "AI effectiveness", "share", x["cache_hit"], 0.995),
        ("run", "Claude's run between interventions", "AI effectiveness", "dec1", hm["run_calls"], None),
        ("unattended", "Sessions with no one stepping in", "AI effectiveness", "share", hm["unattended"], 0.98),
        ("person_share", "Person's share of the time", "AI effectiveness", "share", hm["person_share"], 0.95),
        ("minutes_hour", "Person's minutes per hour of Claude", "AI effectiveness", "dec1",
         hm["minutes_per_hour"], None),
        ("interventions", "Interventions per feature", "AI effectiveness", "dec1", hm["turns_per_feature"], None),
        ("questions", "Questions per feature", "AI effectiveness", "dec1", ai["questions_per_feature"], None),
        ("rejected", "Actions turned down per 100 calls", "AI effectiveness", "dec2",
         dora_numbers.ratio(100 * x["denials"].get("user-rejected", 0), x["tool_calls"]), None),
        ("refusals", "Refusals per 100 calls", "AI effectiveness", "dec2",
         dora_numbers.ratio(100 * sum(x["denials"].values()), x["tool_calls"]), None),
        ("compactions", "Compactions per 100 sessions", "AI effectiveness", "dec1",
         dora_numbers.ratio(100 * x["compactions"], x["sessions"]), None),
        ("thinking", "Thinking", "AI effectiveness", "share", x["thinking_share"], 1.0),
        ("spend", "Spend, last 30 days", "Cost", "money", x["cost_recent"], None),
        ("spend_feature", "Spend per feature", "Cost", "money", x["per_feature"], None),
        ("kloc", "Per 1,000 lines changed", "Cost", "money", x["per_kloc"], None),
    ]
    metrics = [{"key": k, "label": label, "group": group, "fmt": f, "value": v, "cap": cap,
                "band": metrics_guide.spec(label), "profiles": PROFILES.get(k, {})}
               for k, label, group, f, v, cap in rows]
    for key, label, share_ in (("mix_feat", "Features", kind("feat", "perf")),
                               ("mix_fix", "Fixes", kind("fix", "hotfix", "revert")),
                               ("mix_refactor", "Refactoring", kind("refactor")),
                               ("mix_other", "Everything else", 1 - kind("feat", "perf", "fix", "hotfix",
                                                                        "revert", "refactor"))):
        metrics.append({"key": key, "label": label, "group": "Mix", "fmt": "share", "value": share_,
                        "cap": None, "band": None, "profiles": PROFILES[key], "mix": True})
    for m in metrics:
        m["note"] = metrics_guide.TEAM_GUIDE.get(m["key"])
    data = json.dumps({"me": me, "others": list(SIMULATED), "metrics": metrics,
                       "mergeBand": metrics_guide.spec("Merge frequency"),
                       "notes": metrics_guide.TEAM_GUIDE, "sources": metrics_guide.TEAM_SOURCES,
                       "tips": metrics_guide.TEAM_TIPS}).replace("</", "<\\/")
    return dora_page.section(
        "team", "Team", "Developers side by side, over the last %d days." % dora_numbers.WINDOW,
        "<div id=team></div><script type=application/json id=team-data>%s</script>" % data)
