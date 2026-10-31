---
name: sdemo
description: Demo links for checking a feature by hand. `/sdemo` shows the feature's main functionality, its key places; `/sdemo ac` walks through its acceptance criteria one by one. Several links, each opening a page of the feature already signed in as the user it should be seen as (no password), at the address the person can open from where they are — the laptop's <feature>.localhost, or the tailnet's address when they are away on the phone — and under each, what to check there. Use when the user invokes /sdemo, or asks for links to demo, try or check a feature.
argument-hint: "[ac] [feature] [what to show]"
---

# sdemo — links that open the feature signed in, with what to check

`/sdemo [ac] [feature] [what to show]` — the person wants to see the feature
working. Give them **several links**, each one a scenario: a page, the user it
is seen as, and what to check there. They open the links one after another
and have checked the feature.

Two modes:

- **`/sdemo`** — the main functionality: the key places the feature changed,
  the main path first. Not every corner — what someone seeing the feature for
  the first time must see to know it works.
- **`/sdemo ac`** — a walk through the acceptance criteria: every criterion,
  in their order, gets a scenario that shows it, headed by its number (AC1,
  AC2…), and its check lines say what the criterion asks to see. Criteria
  that one page and one user show together may share a scenario — name each
  criterion it covers. A criterion no page can show (a background job, an
  email) is listed at the end with how to check it otherwise.

The links are made by `demo.py` beside this file
(`D="$(readlink -f ~/.claude/skills/sdemo)"`), never by hand: it picks the
address format, encodes the address and the page, and checks the user exists.

## 1. Which feature

The tree this session runs in, when it is a feature's (`python3 $D/demo.py
users` answers). Otherwise the one the person named, or asked about in this
conversation — `--feature <name>` on every call; `demo.py` lists the names
when it cannot tell. Its tree is `~/.claude/sclaude/dev/<name>`: read its
diff there (`git -C`).

## 2. What there is to check

Read what the feature changed before choosing scenarios: `git diff
main...HEAD --stat` and the diff itself, the acceptance criteria
(`python3 $D/demo.py criteria` — sclaude keeps them in the feature's issue),
and what this conversation built.

- Without `ac`: **3–7 scenarios** that between them show the main
  functionality: the main path first, then the other key places, then an
  edge worth eyes only when it is a key place.
- With `ac`: the criteria decide the scenarios, as above; no scenario that
  shows no criterion. Without criteria (no issue, none written) say so and
  fall back to the default mode.

What the person asked to be shown comes first and is never left out.

## 3. Who sees each one

One user for every scenario is fine, and the default: the one whose data
shows the feature best. Switch users where the point is how it looks to
somebody else — the feature shows differently to an owner and a guest, an
admin and a plain user, somebody with data and somebody without; that is what
a demo often has to show, and since every link signs in by itself a second
user costs the person nothing. Not a different user per scenario for its own
sake.

`python3 $D/demo.py users` lists the users of the feature's database. Pick the
user whose data and role show each scenario; read the seed
(`supabase/seed.sql` or the project's seed script) or query the database when
the list alone does not say who is who. Never invent an address: one that does
not exist is refused, not created. When nobody in the database fits a
scenario, say so and say what user it needs — do not create one unasked.

## 4. The links

One call per scenario:

```bash
python3 $D/demo.py link <email> <path> [--feature F]
```

It prints `where:` (laptop or phone, and why), `link:` — the one to give —
and `other:`, the same link for the other place — absent when no phone
address was found, and then `where:` says so. `warn:` lines are said to the
person, not dropped. Where the person is comes from the tailnet: a device of
theirs with traffic now means they are away, and the link goes on the address
a phone opens features at; otherwise `<feature>.localhost`. When the person
says where they are, pass `--where laptop` or `--where phone` — what they say
beats the guess.

## 5. The answer

Say in one line where the links are for (from `where:`), then the scenarios,
numbered, each:

```
**1. <what this shows>** — as <who: role, email>
<link>
- <what to look at or do, and what should happen>
- …
```

With `ac` the heading is the criteria it shows — `**AC1, AC2. <what this
shows>** — as …` — and the answer ends with the criteria no link shows.

Two to four check lines per scenario, concrete: what to click, what should
appear, what must not. End with one line for the case the guess was wrong:
the other place, and the first scenario's `other:` link as its example — or,
with no `other:`, that there is no phone address.

A link can be opened any number of times: the proxy takes a fresh one-time
token on every open. Do not open them in the shared Chrome yourself unasked —
that would switch that browser's session to the scenario's user under the
person's feet.

Not covered: a phone without Tailscale, through the bot's Mini App — there a
feature opens from its card in Telegram, not from a link.
