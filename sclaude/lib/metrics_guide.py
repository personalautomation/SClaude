#!/usr/bin/env python3
#
# What each figure on the metrics page means: why it matters, what to aim for,
# how it is counted — shown under its tile — and the bands that colour it
# good, watch or poor.
#
# Keyed by the tile's label in dora.py's render; a label not here gets no
# note and no colour. The bands are the published ones where a source exists
# (DORA's State of DevOps report, LinearB's engineering benchmarks, the usual
# review and flow guidance) and a stated judgement where none does. A figure
# whose good direction depends on the team — how much is spent, how many
# sessions run — is explained and left uncoloured: colour on it would be an
# opinion dressed as a measurement.
GOOD, WATCH, POOR = "good", "watch", "poor"
HOUR = 3600
DAY = 86400


class Band:
    """A figure's bands. Called with a value it says good, watch or poor;
    `score` puts the same value on 0–100 for the health radar: 100 at the
    good mark and better, 50 at the watch mark, and on down to 0 one more
    such step past it — so a figure just over a line does not fall off a
    cliff, and one far past it reads as far."""

    def __init__(self, distance, kind, a, b):
        # distance(v): 0 inside good, 1 at the watch mark, more beyond.
        self.distance = distance
        # The same bands as data, for the page's own script.
        self.spec = {"kind": kind, "a": a, "b": b}

    def __call__(self, v):
        d = self.distance(v)
        return GOOD if d <= 0 else WATCH if d <= 1 else POOR

    def score(self, v):
        d = self.distance(v)
        return 100.0 if d <= 0 else max(0.0, round(100.0 - 50.0 * d, 1))


def lower(good, watch):
    """Good at or under `good`, watch up to `watch`, poor above."""
    step = (watch - good) or 1
    return Band(lambda v: (v - good) / step, "lower", good, watch)


def higher(good, watch):
    """Good at or over `good`, watch down to `watch`, poor below."""
    step = (good - watch) or 1
    return Band(lambda v: (good - v) / step, "higher", good, watch)


def between(low, high, slack):
    """Good inside [low, high], watch within `slack` of it, poor further."""
    return Band(lambda v: max(low - v, v - high) / (slack or 1), "between", (low, high), slack)


# label: (why it matters and what to decide from it, what to aim for, how it
# is counted, step by step, bands or None)
GUIDE = {
    # --- DORA -------------------------------------------------------------------
    "Deployment frequency": (
        "How often value reaches users. Low frequency means work piles up into big, risky "
        "releases. If it drops: look for what holds releases back — a slow regression, a manual "
        "gate, features too big to ship in parts — and cut features smaller or automate the gate.",
        "Daily or more is Elite, weekly is High.",
        "Vercel's production deployments in state READY over the last 30 days are counted and "
        "divided by 30/7 to give a weekly rate. Builds that failed or were superseded before "
        "going live are not counted. The level compares the daily rate with DORA's bands.",
        higher(1.0, 1 / 7)),
    "Lead time for changes": (
        "How long a finished idea waits before users have it. Long lead time with short coding "
        "time means the waiting is in review or release, not in development — decide where to "
        "add capacity or automation by looking at its stages below.",
        "Under a day is Elite, under a week High.",
        "For every commit a production deploy shipped for the first time (the deploy's commit "
        "against every earlier deploy's, so a redeploy after a rollback ships nothing new), the "
        "clock starts at the first commit of its pull request — or the commit itself if it went "
        "to main directly — and stops when the deploy went live. The median over the changes "
        "shipped in the last 30 days.",
        lower(DAY, 7 * DAY)),
    "Change failure rate": (
        "How often a release hurts users — the price paid for speed. Rising: slow down and "
        "invest in the regression suite or preview checks before shipping more; steady and low: "
        "there is room to ship faster.",
        "5% or less is Elite.",
        "Production deploys in the last 30 days after which production was rolled back, over all "
        "production deploys then. A rollback is found by the incident comment sclaude writes on "
        "the feature's issue, or in the feature's own record when GitHub cannot be asked.",
        lower(0.05, 0.15)),
    "Time to restore": (
        "When something breaks, how long users live with it. Long restore times call for "
        "faster detection (production regression right after deploy) and one-step rollbacks.",
        "Under an hour is Elite.",
        "For each rollback, the time from the deploy that was serving production to the moment "
        "the rollback's incident comment was written; the median over the last 30 days. No "
        "rollbacks means nothing to measure.",
        lower(HOUR, DAY)),
    "Rework rate": (
        "DORA's fifth key since 2024: releases spent fixing what was already out are releases "
        "not spent on new value. High: features ship before they are ready — tighten the "
        "acceptance criteria and the preview check rather than fixing in production.",
        "Under 10%.",
        "Each production deploy with changes is checked: it is rework when every change in it "
        "was a fix to production — a later pull request of a feature that had already shipped, "
        "a pull request from a fix/ branch, or a fix committed straight to main. A `fix:` "
        "commit inside a new feature's own pull request is that feature's work. Rework deploys "
        "over deploys with changes, last 30 days.",
        lower(0.10, 0.20)),
    "Hotfix rate": (
        "A release that needs another within a day was not ready. High: look at what the "
        "hotfixes fixed — a missing test, a skipped preview check, a migration — and close that "
        "gap.",
        "Under 10%.",
        "A production deploy counts when another deploy within the next 24 hours shipped "
        "rework (as defined for the rework rate). Such deploys over all deploys, last 30 days.",
        lower(0.10, 0.20)),
    "Lead time, 90th percentile": (
        "The median hides the changes that got stuck; the tail is what users and stakeholders "
        "remember. A long tail with a short median means a few features stall — find them in "
        "the deploy table and see what they waited on.",
        "Under two days.",
        "The same per-change lead time as above; the value below which 90% of the changes of "
        "the last 30 days fall.",
        lower(2 * DAY, 7 * DAY)),
    "Batch size": (
        "How many changes go out together. Big batches are harder to review, test and roll back, "
        "and a failure hides among many changes. Large: deploy more often, in smaller pieces.",
        "Five or fewer.",
        "For each production deploy, the number of commits it put on production for the first "
        "time; the median over deploys with changes, last 30 days.",
        lower(5, 15)),
    "Days with a deploy": (
        "Shipping as a habit rather than an event. Few days with a deploy and big batches go "
        "together; spreading deploys out lowers each one's risk.",
        "Half the days or more.",
        "Calendar days (local time) with at least one production deploy, over the 30 days.",
        higher(0.5, 0.2)),
    "Time between deploys": (
        "Long gaps let changes pile up. Read it with batch size: a long gap and a big batch mean "
        "releases are being saved up.",
        "A day or less.",
        "The time between consecutive production deploys in the last 30 days; the median.",
        lower(DAY, 7 * DAY)),
    "Production suite green": (
        "Stands in for DORA's reliability: whether production works after each release. Below "
        "target: production differs from preview in a way the tests feel — data, configuration, "
        "secrets — find it before the next deploy.",
        "95% or more.",
        "The production regression sclaude runs after each production deploy of a finished "
        "feature: runs that passed over all runs, from each feature's record.",
        higher(0.95, 0.85)),

    # --- a pull request's way ---------------------------------------------------
    "Coding time": (
        "How long work stays private before anyone can look at it. Long coding time means late "
        "feedback and big pull requests — open the pull request earlier, or split the feature.",
        "Under a day.",
        "For each pull request merged in the last 30 days, from its first commit's author date "
        "to the pull request's creation; the median.",
        lower(DAY, 3 * DAY)),
    "Pickup time": (
        "How long a pull request waits for its first answer. Long pickup is idle work; it is "
        "fixed by review automation or an agreed review slot, not by working faster.",
        "Under an hour.",
        "From the pull request's creation to its first answer — a review, an inline thread or "
        "a comment, a bot's included; the median over pull requests merged in the last 30 days.",
        lower(HOUR, DAY)),
    "Approve time": (
        "The review's own length, from first answer to approval. Long: findings are many or "
        "slow to settle — look at review rounds.",
        "Under a day.",
        "From the first answer to the first approving review. Blank when nobody approves — "
        "in a one-person team the person merges after the automatic review instead.",
        lower(DAY, 3 * DAY)),
    "Merge time": (
        "A reviewed pull request that waits to merge goes stale and conflicts. Long merge time "
        "points at a gate after review — QA, a manual check, a release window.",
        "Under a day.",
        "From the approval — or, with none, the first answer — to the merge; the median.",
        lower(DAY, 3 * DAY)),
    "Review time": (
        "The whole of review, where most lead time is usually lost. Compare with coding time: "
        "if review is longer, invest in the review rather than in coding speed.",
        "Under half a day.",
        "From the pull request's creation to its approval, or to its merge where nobody "
        "approves; the median.",
        lower(12 * HOUR, 2 * DAY)),
    "Deploy time": (
        "Merged code that is not released is inventory: done, paid for, earning nothing. Long "
        "deploy time means releases wait for a batch or a person.",
        "Under an hour.",
        "From the merge to the first production deploy that carried the pull request's merge "
        "commit; the median.",
        lower(HOUR, DAY)),
    "PR aging": (
        "How long a pull request stays open, start to finish. Old pull requests conflict, get "
        "re-reviewed and lose context — close or split long-lived ones.",
        "Under a day.",
        "From creation to merge, for pull requests merged in the last 30 days; the median.",
        lower(DAY, 3 * DAY)),
    "Merge frequency": (
        "Many small merges keep everyone on the same code and make each review small. Low: "
        "work is batched into big pull requests.",
        "Two or more a week per author.",
        "Pull requests merged in the last 30 days, divided by the number of their authors and "
        "by 30/7.",
        higher(2, 1)),
    "PR maturity": (
        "How finished a pull request was when it was opened. Low maturity means the real work "
        "happened in review — which is slow and expensive; finish and self-check before opening.",
        "80% or more of its lines written before it opens.",
        "For each merged pull request, the lines (added plus removed) of its commits made before "
        "it was opened, over the lines of all its commits; summed over pull requests merged in "
        "the last 30 days. Asked of GitHub once per pull request.",
        higher(0.8, 0.6)),
    "PRs without review": (
        "Code that reaches main unseen is the code most likely to break it. Any share above "
        "zero is a process gap: make the review a required check.",
        "Under 5%.",
        "Pull requests merged in the last 30 days with no review, no inline thread and no "
        "comment at all, over all merged.",
        lower(0.05, 0.15)),
    "Review threads resolved": (
        "Every finding settled is one not forgotten. Unresolved threads at merge are known "
        "issues shipped.",
        "90% or more.",
        "Resolved review threads over all review threads, on pull requests merged in the last "
        "30 days.",
        higher(0.9, 0.7)),

    # --- flow -------------------------------------------------------------------
    "Features shipped": (
        "Throughput — features that reached users, not features started. Falling with steady "
        "effort means features are getting bigger or stuck; check the time per feature below.",
        "Steady or rising week on week.",
        "Finished features (sclaude's record of `sclaude done`) whose cycle reached production, "
        "ended in the last 30 days. Per complexity: the same features summed in standard "
        "features.", None),
    "Feature cycle time": (
        "How long one feature takes through sclaude's whole cycle. Use it to forecast: a new "
        "feature of standard size takes about this long. Rising: see which step grew in the "
        "chart of where the time goes.",
        "Under a day.",
        "From each finished feature's record: the time of its plan, code, pull request and "
        "review steps plus its regression stages, summed; the median. Per complexity, each "
        "feature's time is first divided by its size in standard features.",
        lower(DAY, 7 * DAY)),
    "Pull requests per feature": (
        "More than one pull request means the feature went round again — after a rollback, a "
        "QA hand-back or a retrospective. High: the first pass misses something regularly.",
        "1.2 or fewer.",
        "Merged pull requests per finished feature, matched by the feature's branch name.",
        lower(1.2, 1.5)),
    "Pull request size": (
        "Big pull requests are reviewed worse and slower, and break more. Large: split features "
        "into smaller deliverable pieces.",
        "Under 400 lines.",
        "Lines added plus removed per pull request merged in the last 30 days; the median.",
        lower(400, 1000)),
    "Builds": (
        "A failing build stops every preview and release behind it. Failures here point at "
        "configuration or dependencies, not at features.",
        "Under 5% failed.",
        "Every Vercel deployment — preview and production — created in the last 30 days; the "
        "colour is by the share in state ERROR.",
        lower(0.05, 0.15)),
    "Build time": (
        "Slow builds slow every preview, every regression and every release. Long: cache "
        "dependencies, trim the build.",
        "Under ten minutes.",
        "From Vercel's build start to ready, for deployments of the last 30 days; the median.",
        lower(10 * 60, 30 * 60)),
    "Features dropped": (
        "A dropped feature is work paid for and thrown away. High: features start before they "
        "are understood — spend longer on the plan, or validate the idea first.",
        "Under 10%.",
        "Features ended with `sclaude drop`, over all features that ended, all time, from "
        "sclaude's records.",
        lower(0.10, 0.25)),
    "Commits": (
        "Activity, not value — useful only next to what shipped. Many commits and little shipped "
        "means churn.",
        "No target.",
        "Non-merge commits on main in the last 30 days.", None),
    "Time to market": (
        "From asking for something to having it: what a requester actually experiences. Long "
        "with a short cycle time means the wait is before work starts — prioritise the queue.",
        "Under two weeks.",
        "For each finished feature that reached production: from its issue's creation on GitHub "
        "to the end of its cycle; the median. Per complexity, divided by its size first.",
        lower(14 * DAY, 42 * DAY)),
    "Time in the queue": (
        "Waiting before anyone starts is the cheapest delay to remove — it needs a decision, "
        "not effort. Long: take fewer requests in, or start the oldest first.",
        "Under a week.",
        "From the issue's creation to the first Claude session in its feature's worktree; the "
        "median over finished features.",
        lower(7 * DAY, 30 * DAY)),
    "Flow efficiency": (
        "The share of a feature's cycle spent working, the rest waiting. Low: the cycle is "
        "dominated by waits — for review, QA, a person — and adding more AI speed changes "
        "little; remove the waits.",
        "40% or more; 15% is common in industry.",
        "For each finished feature: the time Claude spent in the model and in tools (from the "
        "cost record of its sessions) over its cycle time, capped at 100%; the median.",
        higher(0.4, 0.15)),
    "Features at once": (
        "Work in progress. Too many features at once stretch every one's lead time and split "
        "the person's attention. High: finish before starting.",
        "Three or fewer on a day.",
        "For each day, the features (worktrees) with at least one Claude session started that "
        "day; the most on any day, and the median over active days.",
        lower(3, 5)),

    # --- testing / defects / mix -------------------------------------------------
    "Escaped defects": (
        "Defects found in production cost the most to find and to fix. Rising: the earlier "
        "gates (local and preview regression) miss what production catches — add those checks "
        "earlier.",
        "Under 10%.",
        "Production rollbacks, over everything the regression found to fix across finished "
        "features: features whose local or preview stage needed a fixing session, plus the "
        "rollbacks.",
        lower(0.10, 0.20)),
    "Defect density": (
        "Bugs relative to how much code changed. Rising with steady change volume means quality "
        "slips; compare with tests in new lines.",
        "Under 0.5 per 1,000 lines.",
        "Issues of type Bug, or with a label containing \"bug\", among the issues read, per "
        "1,000 lines changed on main since the first Claude session.",
        lower(0.5, 1.0)),
    "Bug resolution time": (
        "How long a reported bug stays a user's problem. Long: bugs wait behind features — "
        "reserve capacity for them.",
        "Under three days.",
        "From creation to closing, for bug issues that are closed; the median.",
        lower(3 * DAY, 14 * DAY)),
    "Reopened issues": (
        "Closed work that had to be reopened was not done. sclaude reopens an issue when a "
        "feature returns after its merge, so this also counts rollbacks and QA hand-backs.",
        "Under 5%.",
        "Issues with at least one reopening in their timeline, over the closed issues read.",
        lower(0.05, 0.15)),
    "Rollback ratio": (
        "Releases that had to be taken back — the change failure rate seen as a share.",
        "Under 5%.",
        "Production deploys followed by a rollback, over all production deploys, last 30 days.",
        lower(0.05, 0.15)),
    "Refactor work": (
        "Code that is never tidied gets slower to change. Too little: schedule refactoring; too "
        "much: the design may be unsettled.",
        "10–20% of changes.",
        "Changes shipped in the last 30 days whose Conventional Commits type is `refactor`, over "
        "all changes shipped.",
        between(0.10, 0.20, 0.05)),
    "Support work": (
        "Keeping the lights on — fixes, chores, CI, dependencies — against new value. High: "
        "quality or tooling debt is eating capacity; invest there.",
        "Under 30%.",
        "Changes shipped in the last 30 days of type fix, hotfix, revert, chore, ci, build or "
        "deps, over all changes shipped.",
        lower(0.30, 0.50)),
    "Planned work": (
        "Work that came from an issue was asked for; the rest was unplanned. Low: much effort "
        "goes to things nobody prioritised.",
        "80% or more.",
        "Changes shipped in the last 30 days that came in a pull request whose branch names an "
        "issue number, over all changes shipped.",
        higher(0.8, 0.6)),
    "Changes through a PR": (
        "Change control: every change reviewed before it reaches main. Below target: direct "
        "commits bypass review — protect the main branch.",
        "95% or more.",
        "Changes shipped in the last 30 days that reached main inside a merged pull request "
        "(its squash commit, or any commit of its branch when merged with a merge commit), over "
        "all changes shipped.",
        higher(0.95, 0.8)),
    "Regression green first time": (
        "Whether the code was right before it was tested. Low: the code step leaves work for "
        "the regression — improve the plan's test list or the code step's own checks.",
        "80% or more.",
        "Regression stages (local, preview, production) of finished features that passed "
        "without any fixing session, over all stages that ran.",
        higher(0.8, 0.6)),
    "Fixing sessions": (
        "Each one is a round trip the code needed after it was written.",
        "As few as possible.",
        "Claude sessions sclaude started to fix a red regression, summed over finished "
        "features' records.", None),
    "Tests in new lines": (
        "New code without tests is tomorrow's regression. Low: ask the plan for tests with "
        "every criterion.",
        "25% or more of added lines.",
        "Lines added in the last 30 days in test paths (tests/, __tests__/, e2e/, spec/, "
        "*.test.*, *.spec.*, *_test.*), over all lines added.",
        higher(0.25, 0.10)),
    "Reverts": (
        "A revert is a change that should not have been made.",
        "None.",
        "Commits on main in the last 30 days whose subject starts with Revert.",
        lower(0, 2)),
    "Migrations": (
        "Schema changes are the riskiest to roll back. Many: check the rollback figures and the "
        "down blocks.",
        "No target — read with the rollback figures.",
        "Files added in the last 30 days under a migrations/ directory.", None),

    # --- review -----------------------------------------------------------------
    "Review threads per PR": (
        "Findings per pull request: fewer means the code was right before review. Rising: the "
        "code step leaves more for the review to catch.",
        "Ten or fewer.",
        "Review threads on each pull request merged in the last 30 days; the median.",
        lower(10, 20)),
    "Review rounds per feature": (
        "Each round is a full review pass. Many rounds mean the fixes kept bringing new "
        "findings — the review is not converging. Decide whether to cap rounds, or improve the "
        "code step so fewer findings appear.",
        "Three or fewer.",
        "Runs of the automatic review workflow on the feature's branch, over every pull request "
        "the feature took — rounds, not sessions: one session can carry several. Without runs, "
        "threads more than ten minutes apart start a new round. The median over finished "
        "features. Per complexity, each feature's rounds over its size first.",
        lower(3, 8)),
    "Review threads per feature": (
        "How much the review found in a feature across all its pull requests. Compare between "
        "features per complexity: a small feature with many threads was written poorly.",
        "Fifteen or fewer.",
        "Review threads on every pull request of a finished feature, summed; the median. Per "
        "complexity, divided by the feature's size first.",
        lower(15, 40)),
    "Threads closed without a fix": (
        "Findings the author declined. A high share means the reviewer raises noise — tune its "
        "rules so attention goes to real findings.",
        "Under 10%; above 60% the reviewer has turned to noise.",
        "Threads resolved with the author's decline reply, as the review report classifies "
        "them, over all threads of finished features.",
        lower(0.10, 0.25)),
    "Threads still open": (
        "A finding nobody settled before the merge is a known problem shipped.",
        "Under 2%.",
        "Threads neither resolved nor marked as left for the person, over all threads of "
        "finished features.",
        lower(0.02, 0.10)),
    "Acceptance criteria": (
        "Criteria written up front are what QA checks the feature against. Few ticked: QA "
        "does not use them — either tick them or drop the step.",
        "Every criterion ticked by QA.",
        "Checkboxes in the issue's acceptance-criteria comment of each finished feature; the "
        "colour is by the share ticked.",
        higher(0.9, 0.5)),

    # --- requirements -----------------------------------------------------------
    "Requirements changed in development": (
        "A target that moves after work starts is paid for twice. High: plan longer with the "
        "requester, or split features so that a change lands in a new one.",
        "Under 10% of features.",
        "Development starts when the plan is approved — the moment sclaude posts the acceptance "
        "criteria. The issue's description, the User request comment and the criteria as they "
        "stood then are joined and compared with how they ended (GitHub keeps every version of "
        "an edited body); ticks in the criteria's boxes are ignored. A feature counts when a "
        "fifth of that text was rewritten, a criterion was added or dropped, or two "
        "requirements were added under \"Added during development\".",
        lower(0.10, 0.25)),
    "Requirements added in development": (
        "Each one is scope that arrived after the plan.",
        "No target — read with the share above.",
        "Bullet lines under \"Added during development\" in each finished feature's User "
        "request comment, which the code step writes for every new thing the person asks for.",
        None),
    "Requirements unclear at the start": (
        "A feature that needed as many questions as it has criteria was not described well "
        "enough to start. High: improve issue templates, or have someone groom issues before "
        "they enter the cycle.",
        "Under 20% of features.",
        "For each finished feature: the clarifying questions in its plan sessions — each "
        "question of an AskUserQuestion call counted separately — over its acceptance criteria "
        "(its estimated size where it has none). It counts when that ratio is 1 or more.",
        lower(0.2, 0.4)),
    "Questions per criterion": (
        "Clarifying questions relative to how much was asked for: how much the description left "
        "out, independent of the feature's size.",
        "Under 0.5.",
        "Questions in the plan sessions over the feature's acceptance criteria; the median over "
        "finished features.",
        lower(0.5, 1.0)),
    "Clarifying questions in planning": (
        "How much had to be asked before the work could be planned.",
        "Three or fewer per feature.",
        "Questions Claude asked the person in the feature's plan sessions, each question of an "
        "AskUserQuestion call counted; the median. Per complexity, divided by the size first.",
        lower(3, 8)),
    "Request grew in planning": (
        "The agreed request against what the issue first said. A large growth means the issue "
        "was a title rather than a description.",
        "Under 2×.",
        "Words of the User request comment (without what was added during development) over the "
        "words of the issue's description; the median over finished features.",
        lower(2, 4)),

    # --- code and project health ------------------------------------------------
    "Source lines": (
        "The size of what has to be maintained.",
        "No target.",
        "Non-blank lines of tracked source files, by extension, vendored code excluded.", None),
    "Comment lines": (
        "Some comments explain why; too few leave intent unknown, too many go stale.",
        "10–35%.",
        "Lines that begin with the language's comment mark (#, //, /*, *, --), over non-blank "
        "source lines.",
        between(0.10, 0.35, 0.05)),
    "Large files": (
        "Files past 500 lines are hard to read and to review. Many: split them when next "
        "touched.",
        "Under 5% of source files.",
        "Tracked source files longer than 500 lines; the colour is by their share of source "
        "files.",
        lower(0.05, 0.10)),
    "Tests": (
        "How much of the code exists to check the rest.",
        "20% or more.",
        "Non-blank lines in test paths, over all non-blank source lines.", higher(0.20, 0.10)),
    "Issues under a parent": (
        "Issues tied to an epic show what they belong to, and let progress be read per goal.",
        "50% or more.",
        "Issues with a parent issue, over the issues read from GitHub.", higher(0.5, 0.25)),
    "Branches named after an issue": (
        "Traceability from code to the request behind it. Low: work happens outside the "
        "issue tracker.",
        "90% or more.",
        "Pull request branches whose name carries an issue number (feat/12-…), over all pull "
        "request branches read.",
        higher(0.9, 0.7)),
    "Open issues with an owner": (
        "Work nobody owns is work nobody does.",
        "95% or more.",
        "Open issues with at least one assignee, over open issues read.", higher(0.95, 0.8)),
    "Deferred friction age": (
        "Friction put off for the monthly review should not wait forever; old entries are rules "
        "that keep getting in the way.",
        "Under a month.",
        "Days since each deferred friction entry's date, across the product's deferred files; "
        "the median and the oldest.",
        lower(30, 60)),

    # --- health -----------------------------------------------------------------
    "Health index": (
        "One number for the whole, to compare month with month. It says whether things improve "
        "overall; the radar says where.",
        "75 or more.",
        "Every figure on the radar is scored 0–100 by its own bands: 100 at the good mark or "
        "better, 50 at the watch mark, falling to 0 one more band-width beyond. A direction is "
        "the mean of its figures' scores; the index is the mean of the directions.",
        higher(75, 50)),
    "Imbalance": (
        "A good average can hide one direction far behind the rest — and that one sets the "
        "pace. Large: put the next improvement into the weakest direction rather than the "
        "strongest.",
        "Under 25 points.",
        "The best direction's score minus the worst direction's.", lower(25, 50)),
    "Weakest direction": (
        "Where an hour of effort moves the whole most.",
        "Every direction 75 or more.",
        "The direction with the lowest score; point at its dot on the radar for its figures.",
        higher(75, 50)),
    "Spend trend": (
        "Whether a standard feature is getting cheaper to deliver.",
        "1 or less: no dearer than the weeks before.",
        "The last week's spend over the standard features it shipped, divided by the median "
        "of the same figure for the weeks before it.",
        lower(1.0, 1.5)),

    # --- the person and Claude ---------------------------------------------------
    "Claude's run between interventions": (
        "How far Claude gets on its own before it needs the person. Short runs mean constant "
        "supervision — find what Claude asks about and put the answer in the rules or the plan.",
        "Ten tool calls or more.",
        "In every session's transcript: each time the person stepped in — a message typed after "
        "Claude's turn, or an answer to Claude's question — the tool calls Claude made since "
        "the previous time are counted. The median over all such turns.",
        higher(10, 4)),
    "Time Claude runs alone": (
        "The stretch a person can spend on something else.",
        "Ten minutes or more.",
        "Between two consecutive turns of the person in a session: the clock time between them, "
        "less the time the person took over the second. The median.",
        higher(10 * 60, 3 * 60)),
    "Sessions with no one stepping in": (
        "Work that finished without a person at all — the fully delegated part.",
        "60% or more of the sessions sclaude starts.",
        "Sessions sclaude started (any session named after a step) in which the person never "
        "typed or answered, over all of them. Sessions run by hand are left out.",
        higher(0.6, 0.3)),
    "Person's share of the time": (
        "How much of the joint effort was the person's. High: the person is the bottleneck; "
        "look at which steps need them most.",
        "Under 25%.",
        "The person's time is, for each turn, from Claude's last line to the person's reply, "
        "capped at 30 minutes (beyond that they were away). Claude's time is its own cost "
        "record's time in the model and in tools. Person over both.",
        lower(0.25, 0.5)),
    "Person's minutes per hour of Claude": (
        "The person's cost of an hour of Claude's work — the leverage of delegating.",
        "Fifteen minutes or less.",
        "The person's time (as above) in minutes, over Claude's time in hours.",
        lower(15, 30)),
    "Interventions per feature": (
        "How often a feature needed the person. Compare per complexity: a small feature with "
        "many interventions was poorly specified or hit a gap in the rules.",
        "Ten or fewer.",
        "The person's turns in the sessions of a finished feature's worktree, summed; the "
        "median. Per complexity, divided by the feature's size first.",
        lower(10, 25)),
    "Person's time per feature": (
        "What a feature cost the person in attention.",
        "Half an hour or less.",
        "The person's time (each wait capped at 30 minutes) in a finished feature's sessions, "
        "in minutes; the median.",
        lower(30, 90)),
    "Autonomy": (
        "How much Claude does per thing a person has to say.",
        "20 or more.",
        "All tool calls over all human inputs: typed messages (less the opening prompt of each "
        "session sclaude started), answers to Claude's questions and actions the person turned "
        "down.", higher(20, 5)),
    "Questions per feature": (
        "Claude asking is cheaper than Claude guessing — but every question waits for a person.",
        "No target.",
        "AskUserQuestion calls in a finished feature's sessions; the median.", None),
    "Sessions by hand": (
        "Sessions a person started outside sclaude's cycle. High: much work bypasses the "
        "process and its measurements.",
        "Under 30%.",
        "Sessions whose name carries no step, over all sessions.", lower(0.3, 0.6)),
    "Adoption": (
        "The share of the people committing who use Claude.",
        "80% or more.",
        "Commit authors of the last 30 days with at least one commit signed by a Claude session, "
        "over all commit authors.", higher(0.8, 0.5)),

    # --- Claude at work ----------------------------------------------------------
    "Sessions": (
        "How much of the work runs through Claude.",
        "No target.",
        "Claude Code transcripts in the product's checkout and worktrees, subagents aside.", None),
    "Subagents": (
        "Work Claude handed to helpers of its own.",
        "No target.",
        "Subagent transcripts beside the sessions.", None),
    "Tool calls": (
        "Actions Claude took: commands run, files read and edited.",
        "No target.",
        "Tool calls in every transcript, each counted once however often it is logged.", None),
    "Commits by Claude": (
        "The share of the code that Claude wrote.",
        "No target.",
        "Commits on main in the last 30 days signed by a Claude session — a Sclaude-Session or "
        "Claude-Session trailer, or a Claude co-author — over all commits.", None),
    "Subagents per session": (
        "How much a session spreads its work.",
        "No target.",
        "Subagents over sessions.", None),
    "Sessions per week": (
        "Active usage frequency.",
        "No target.",
        "Sessions started in the last 30 days, per week.", None),
    "Tokens per week": (
        "Usage volume.",
        "No target.",
        "Input, output and cache tokens from the cost records of sessions started in the last "
        "30 days, per week.", None),
    "Session length": (
        "Short sessions are focused; long ones accumulate context and cost.",
        "No target.",
        "From a session's first to its last line; the median.", None),

    # --- working with Claude, per person (the team part) ------------------------
    "Commits written by Claude": (
        "How much of a person's code Claude writes — the depth of adoption. Low: they still "
        "type most of it themselves; pair them with someone who delegates more.",
        "70% or more.",
        "Commits signed by a Claude session over all the person's commits, last 30 days.",
        higher(0.7, 0.4)),
    "Subagent use": (
        "Subagents search and read in parallel without filling the main session's context. "
        "Low: long sessions do everything themselves and run out of context sooner.",
        "A third of sessions or more.",
        "Sessions that started at least one subagent (Agent or Task), over all sessions.",
        higher(0.3, 0.1)),
    "Skill use": (
        "Skills carry the team's way of doing a task — a review, a pull request, a deploy. "
        "Low: the person re-explains procedures that already exist.",
        "A third of sessions or more.",
        "Sessions that ran a skill, over all sessions.", higher(0.3, 0.1)),
    "Plan mode use": (
        "Planning before editing catches the misunderstanding while it is cheap. Low on large "
        "features: work starts before it is agreed.",
        "A quarter of sessions or more.",
        "Sessions that entered or left plan mode, over all sessions.", higher(0.25, 0.08)),
    "MCP tool use": (
        "Tools beyond the shell — a browser, a tracker, a database — let Claude check its own "
        "work. Low: the person checks for it.",
        "No fixed target; read against the team.",
        "Sessions that called an MCP tool, over all sessions.", None),
    "Top-model share of spend": (
        "The largest model for everything is the most expensive way to work; small tasks and "
        "subagents run as well on smaller ones.",
        "70% or less.",
        "Spend on the largest model family over all spend, from the cost records.",
        lower(0.7, 0.9)),
    "Actions turned down per 100 calls": (
        "Each one is Claude doing what the person did not want — a sign the task said too "
        "little. High: state constraints in the first message, or widen what is allowed.",
        "Under 0.5.",
        "Tool calls the person rejected, per 100 tool calls.", lower(0.5, 2)),
    "Refusals per 100 calls": (
        "Claude running into the rules: blocked commands, permission rules. High: the rules "
        "and the person's habits disagree — fix one of them.",
        "Under 1.",
        "Tool calls refused by a permission rule, auto mode or the person, per 100 tool calls.",
        lower(1, 3)),
    "Compactions per 100 sessions": (
        "A compaction means a session outgrew its context and was summarised, losing detail. "
        "High: split work into smaller sessions, one step each.",
        "Under 5.",
        "Context compactions per 100 sessions.", lower(5, 20)),

    # --- cost -------------------------------------------------------------------
    "Spend": (
        "What Claude cost. Read it per result, below, rather than in total.",
        "Falling per result while results hold.",
        "Claude Code's own cost record in each transcript: the last record of each run, summed. "
        "It includes the subagents' cost.", None),
    "Per finished feature": (
        "The cost of one result — use it to price new features.",
        "Falling over time.",
        "The spend of all sessions in a finished feature's worktree; the median. Per "
        "complexity, divided by the feature's size first.", None),
    "Per production deploy": (
        "Spend for each release.",
        "Falling over time.",
        "Spend of sessions started in the last 30 days over the production deploys then.", None),
    "Per merged pull request": (
        "Spend for each merged change set.",
        "Falling over time.",
        "Spend of sessions started in the last 30 days over pull requests merged then.", None),
    "Per 1,000 lines changed": (
        "Spend relative to output volume.",
        "Falling over time.",
        "Spend in the last 30 days over thousands of lines (added plus removed) on main.", None),
    "Cache hit rate": (
        "Input read from the prompt cache costs a tenth of fresh input. Falling: sessions are "
        "restarted or prompts change too often.",
        "90% or more.",
        "Cache reads over all input tokens (fresh, cache reads and cache writes), from the cost "
        "records.", higher(0.9, 0.7)),
    "Thinking": (
        "How much of the output is reasoning.",
        "No target.",
        "Thinking tokens over output tokens.", None),
    "Output per tool call": (
        "Words per action.",
        "No target.",
        "Output tokens over tool calls.", None),
    "Time in the model": (
        "Where a session's time goes: thinking, or waiting for tools (tests, builds).",
        "No target.",
        "API time over API and tool time, from the cost records.", None),
}


def lookup(label):
    """The guide's entry for a tile, by its label or the part before a comma
    ("Spend, last 30 days" → "Spend")."""
    return GUIDE.get(label) or GUIDE.get(label.split(",")[0])


def spec(label):
    """A figure's bands as data — {kind, a, b} — or None."""
    entry = lookup(label)
    return entry[3].spec if entry and entry[3] is not None else None


def score(label, raw):
    """The figure on 0–100 by its bands, or None where it has none or is
    unknown."""
    entry = lookup(label)
    if not entry or entry[3] is None or raw is None:
        return None
    return entry[3].score(raw)


def judge(label, raw):
    """good, watch, poor — or None where the figure is not judged or unknown."""
    entry = lookup(label)
    if not entry or entry[3] is None or raw is None:
        return None
    return entry[3](raw)


# --- the team part ------------------------------------------------------------
#
# The team part's figures, per developer. "How" says how each is counted for a
# person, which assumes every developer's sclaude publishes what this machine
# keeps about its own developer: the cycle records (cycles.jsonl, which already
# carry `developer`) and the summaries of the Claude transcripts, one file per
# person in the team's metrics repository (`metrics` in the config). Git and
# GitHub need nothing published: a commit has its author, a pull request its.
TEAM_SOURCES = (
    "Every developer's sclaude publishes its records — the finished features' cycle "
    "records and the summaries of its Claude transcripts — to the team's metrics "
    "repository, one file per person; the page reads them all.")

TEAM_GUIDE = {
    "team_features": (
        "The team's output in one figure; read it with the bus factor before deciding who "
        "takes the next large feature.",
        "Steady or rising.",
        "Finished features in all developers' cycle records, each counted once."),
    "team_lines": (
        "How much code the team changed. A sudden jump with flat feature output means churn or "
        "a large refactor — worth asking which.",
        "No target.",
        "Lines added plus removed by all authors' non-merge commits on main in the last 30 "
        "days."),
    "bus": (
        "How many people the work depends on. One or two means a single absence stalls the "
        "product: pair on the code they hold, or rotate features.",
        "Half the team or more.",
        "Developers sorted by their commits in the last 30 days; the fewest whose commits add up "
        "to half the team's."),
    "team_spend": (
        "What Claude cost the team. Read it per developer below to see whose work is expensive "
        "and why, before setting budgets.",
        "Falling per standard feature.",
        "The cost records of all developers' published transcript summaries, sessions started "
        "in the last 30 days."),
    "features": (
        "Who delivers features. Very uneven counts mean uneven feature sizes, or one person "
        "carrying the roadmap — check per complexity before comparing.",
        "Spread across the team.",
        "Finished features whose cycle record names the developer (sclaude's `developer`, set "
        "from their git identity)."),
    "prs": (
        "Pull requests a person landed — the unit of review load they create for others.",
        "Two or more a week each.",
        "Pull requests merged in the last 30 days whose GitHub author is the developer."),
    "commits": (
        "Activity per person. Many commits and few features may mean work that does not land.",
        "No target.",
        "Non-merge commits on main in the last 30 days whose git author is the developer; a "
        "developer's several emails are mapped to one person."),
    "lines": (
        "How much code each person changes. A high share of the team's lines with a low share "
        "of features means large, slow-to-review changes.",
        "No target.",
        "Lines added plus removed in the developer's non-merge commits on main, last 30 days."),
    "bugs": (
        "Who fixes what breaks. If one person fixes most bugs, they are the safety net — and "
        "the others may not see the consequences of their own changes.",
        "Spread, or a deliberate rotation.",
        "The developer's commits shipped in the last 30 days with Conventional Commits type "
        "fix, hotfix or revert."),
    "cycle": (
        "How long a person's features take. Compare per complexity: a long cycle on small "
        "features is a person who needs help, or a part of the code that is hard.",
        "Under a day per standard feature.",
        "From the developer's cycle records: the steps' and regression stages' time of each "
        "finished feature, summed; the median."),
    "lead": (
        "How long a person's changes wait before users have them — usually the review and "
        "release they depend on, not their own speed.",
        "Under a day.",
        "The lead time of each change shipped in the last 30 days whose commit the developer "
        "authored, first commit of its pull request to the deploy; the median."),
    "aging": (
        "How long a person's pull requests stay open — where reviews by others are slow.",
        "Under a day.",
        "Pull requests authored by the developer, created to merged; the median."),
    "pr_size": (
        "Who opens big pull requests. Large ones are reviewed worse and slower — coach towards "
        "splitting.",
        "Under 400 lines.",
        "Lines added plus removed in pull requests the developer authored, merged in the last "
        "30 days; the median."),
    "green": (
        "Whose code passes the regression without fixing. Low: their features need a better "
        "plan of tests, or a pair for the risky parts.",
        "80% or more.",
        "Regression stages of the developer's finished features that passed with no fixing "
        "session, over all stages that ran."),
    "rounds": (
        "How many review passes a person's features need. Many: the review keeps finding "
        "things in their code — look at what kinds.",
        "Three or fewer.",
        "Runs of the automatic review on the branches of the developer's finished features, "
        "over all their pull requests; the median."),
    "threads": (
        "How much the review finds in a person's work.",
        "Fifteen or fewer.",
        "Review threads on all pull requests of the developer's finished features, summed per "
        "feature; the median."),
    "escaped": (
        "Whose changes reach production broken. Any: review what the earlier gates missed in "
        "their features.",
        "Under 10%.",
        "Production rollbacks of the developer's features, over everything the regression "
        "found to fix in them."),
    "reopened": (
        "Whose closed work came back.",
        "Under 5%.",
        "Issues of the developer's features reopened at least once, over their closed ones."),
    "run": (
        "How far Claude gets on its own for each person. Short: they step in often — maybe "
        "their tasks are vaguer, maybe they supervise more than needed. Share the rules of "
        "whoever runs longest.",
        "Ten tool calls or more.",
        "From the developer's transcript summaries: the tool calls Claude made between two of "
        "that developer's turns; the median."),
    "person_share": (
        "How much of each person's joint effort with Claude is their own time.",
        "Under 25%.",
        "From the developer's transcript summaries: their time (from Claude's last line to their "
        "reply, each capped at 30 minutes) over theirs and Claude's model and tool time."),
    "interventions": (
        "How often a person's features needed them.",
        "Ten or fewer.",
        "The developer's turns in the sessions of their finished features; the median."),
    "questions": (
        "How much Claude had to ask each person. Many: their issues start under-described.",
        "No target.",
        "AskUserQuestion calls in the developer's finished features' sessions; the median."),
    "sessions": (
        "How much each person works through Claude.",
        "No target.",
        "Sessions in the developer's transcript summaries started in the last 30 days."),
    "person_hours": (
        "The attention each person gave Claude.",
        "No target.",
        "The developer's time across all their turns, each capped at 30 minutes, in hours."),
    "spend": (
        "What each person's work with Claude cost.",
        "Falling per standard feature.",
        "The cost records in the developer's transcript summaries, sessions of the last 30 days."),
    "spend_feature": (
        "The price of a person's feature. Compare per complexity; a much higher price is worth "
        "a look at how they work with Claude.",
        "Falling over time.",
        "Spend of the sessions in each of the developer's finished features' worktrees; the "
        "median."),
    "leverage": (
        "Features a person delivers per hour of their own attention — the leverage they get "
        "from Claude.",
        "Rising.",
        "The developer's finished features over their hours with Claude."),
    "ai_commits": (
        "How much of each person's code Claude writes — adoption in practice, not in principle.",
        "70% or more.",
        "The developer's commits signed by a Claude session over all their commits, last 30 "
        "days, from git."),
    "sessions_week": (
        "How often each person reaches for Claude.",
        "No target; read with the effectiveness rows.",
        "Sessions in the developer's transcript summaries started in the last 30 days, per week."),
    "tokens_week": (
        "How much each person works through Claude, by volume.",
        "No target.",
        "Input, output and cache tokens of the developer's sessions, last 30 days, per week."),
    "subagents": (
        "Whether a person delegates searching and reading to subagents.",
        "A third of sessions or more.",
        "The developer's sessions that started a subagent, over their sessions."),
    "skills": (
        "Whether a person uses the team's packaged procedures.",
        "A third of sessions or more.",
        "The developer's sessions that ran a skill, over their sessions."),
    "plan": (
        "Whether a person plans before Claude edits.",
        "A quarter of sessions or more.",
        "The developer's sessions that used plan mode, over their sessions."),
    "mcp": (
        "Whether a person lets Claude use tools beyond the shell to check its work.",
        "Read against the team.",
        "The developer's sessions that called an MCP tool, over their sessions."),
    "top_model": (
        "Whether a person matches the model to the task.",
        "70% or less.",
        "Spend on the largest model family over the developer's spend."),
    "cache": (
        "Input read from the prompt cache costs a tenth. Low: sessions are restarted or the "
        "prompt keeps changing mid-task.",
        "90% or more.",
        "Cache reads over all input tokens in the developer's cost records."),
    "unattended": (
        "How much of a person's work runs without them.",
        "60% or more.",
        "The developer's sclaude sessions with no turn of theirs, over all their sclaude "
        "sessions."),
    "minutes_hour": (
        "A person's cost per hour of Claude's work.",
        "Fifteen minutes or less.",
        "The developer's time over Claude's time in their sessions, per hour."),
    "rejected": (
        "How often Claude does what the person did not want.",
        "Under 0.5 per 100 calls.",
        "Tool calls the developer rejected, per 100 tool calls of their sessions."),
    "refusals": (
        "How often Claude hits the rules in a person's sessions.",
        "Under 1 per 100 calls.",
        "Refused tool calls per 100 tool calls of the developer's sessions."),
    "compactions": (
        "How often a person's sessions outgrow their context.",
        "Under 5 per 100 sessions.",
        "Context compactions per 100 of the developer's sessions."),
    "thinking": (
        "How much of Claude's output in a person's sessions is reasoning.",
        "No target.",
        "Thinking tokens over output tokens in the developer's cost records."),
    "kloc": (
        "What a thousand lines of a person's code cost in Claude.",
        "Falling over time.",
        "The developer's spend over thousands of lines they changed, last 30 days."),
    "merge_freq": (
        "How often a person lands work. Rare merges mean big batches.",
        "Two or more a week.",
        "The developer's merged pull requests in the last 30 days, per week."),
}


# What to suggest when a person's figure is their weak side, in the team part's
# coaching cards. Short and actionable: one habit each.
TEAM_TIPS = {
    "ai_commits": "Hand Claude whole tasks, not snippets: describe the change and let it write "
                  "the code and the commit.",
    "subagents": "Ask Claude to send a subagent for searches and reading, so the main session "
                 "keeps its context for the change.",
    "skills": "Use the team's skills (/pr, /sreview …) instead of re-explaining the procedure.",
    "plan": "Start larger features in plan mode and agree the plan before Claude edits.",
    "mcp": "Let Claude check its own work with the browser and tracker tools.",
    "top_model": "Use a smaller model for small tasks and for subagents.",
    "cache": "Keep a session alive through a task, and avoid changing its instructions midway; "
             "every restart pays for the whole context again.",
    "unattended": "Give the whole task, its constraints and its done-check up front, then let "
                  "it run.",
    "minutes_hour": "Answer in batches: let Claude finish a step before reading along.",
    "rejected": "State constraints in the first message — what not to touch, what not to run.",
    "refusals": "Agree the rules with the team: allow what is safe and routine, so Claude stops "
                "asking.",
    "compactions": "One step per session: plan, code, review in separate sessions.",
    "run": "Write fuller issues and acceptance criteria, so Claude needs you less.",
    "person_share": "Delegate more of the reading and checking to Claude.",
    "questions": "Put the decisions in the issue before the plan starts.",
    "green": "Ask the plan for the tests of every criterion, and run them before the pull request.",
    "rounds": "Run the review locally before pushing, and fix the findings in one pass.",
    "kloc": "Smaller sessions and smaller models for routine changes.",
}
