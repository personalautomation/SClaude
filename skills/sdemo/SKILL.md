---
name: sdemo
description: A feature's demo, played for the person. `/sdemo` records a demo of the feature's main functionality — Playwright signs in as each scenario's user, clicks and types through it, with captions on the page saying what each step shows, where to look and why it matters — and gives one link to a page with a video per scenario, the steps beside it, and "take over" links that open any step's page signed in to go on by hand; `/sdemo ac` walks through the acceptance criteria instead; `/sdemo live` plays it in the laptop's chrome-debug with ⏸ to take over; `/sdemo links` gives plain signed-in links with what to check (`links open` opens them in chrome-debug). Links are for where the person is — the laptop's <feature>.localhost, or the tailnet's address on the phone. Use when the user invokes /sdemo, or asks to demo, show, try or check a feature.
argument-hint: "[ac | delta] [live | links [open]] [feature] [what to show]"
---

# sdemo — the feature, shown

`/sdemo [ac] [live | links [open]] [feature] [what to show]` — the person
wants to see the feature working.

What to show:

- **`/sdemo`** — the main functionality: the key places the feature changed,
  the main path first. Not every corner — what someone seeing the feature for
  the first time must see to know it works. **3–7 scenarios.**
- **`/sdemo ac`** — a walk through the acceptance criteria: every criterion,
  in their order, gets a scenario that shows it, its title headed by its
  number (AC1, AC2…), and checks that say what the criterion asks to see.
  Criteria that one page and one user show together may share a scenario —
  name each criterion it covers. A criterion no page can show (a background
  job, an email) is said at the end with how to check it otherwise. Without
  criteria (no issue, none written) say so and show the main functionality.

- **`/sdemo delta`** — only what changed for the user since the last full
  demo: a short recording to watch instead of the whole one again (section
  4a). Nothing changed for the user — a refactoring, a fix nobody sees, tests —
  and there is no delta: say so, and record nothing.

What the person asked to be shown comes first and is never left out.

How it is shown:

- **default — a recorded demo**: Playwright plays the scenarios headless and
  records them; the person gets one link to a page with a video per
  scenario, its steps beside it (tap one to jump there), what each shows and
  why, and a **take over** link on every step that opens that page signed in
  as that user, to go on by hand. In a session sclaude runs, the link and
  the videos also go to the feature's Telegram topic and to a comment of its
  own on the feature's issue, which replaces the one before; anywhere else
  the link is given here alone.
- **`live`** — the same script, played in the laptop's chrome-debug, a
  window per user with cookies of its own. The page carries ⏸ ▶ ⏭ ⏹: on
  pause the page is the person's, ▶ goes on, ⏹ ends the script and leaves
  the windows signed in. For somebody at the laptop.
- **`links`** — no script: a signed-in link per scenario with what to check
  under it (section 6); **`links open`** also opens them in chrome-debug.

Everything goes through `demo.py` beside this file
(`D="$(readlink -f ~/.claude/skills/sdemo)"`), never by hand: it picks the
address, encodes it, checks the users and runs the player (`play.mjs`).

## 1. Which feature

The tree this session runs in, when it is a feature's (`python3 $D/demo.py
users` answers). Otherwise the one the person named, or asked about in this
conversation — `--feature <name>` on every call; `demo.py` lists the names
when it cannot tell. Its tree is `~/.claude/sclaude/dev/<name>`: read its
diff there (`git -C`).

## 2. What there is to show

Read what the feature changed before choosing scenarios: `git diff
main...HEAD --stat` and the diff itself, the acceptance criteria
(`python3 $D/demo.py criteria` — sclaude keeps them in the feature's issue),
and what this conversation built. For a script, read the components the
steps go through too: the names on buttons, links and fields are what the
steps find them by.

**Desktop and phone.** Show the feature both ways: the main path, and every
place whose layout differs on a phone — a menu that folds, a table that becomes
cards, a dialog that becomes a sheet — get a scenario with `viewport: "phone"`
beside the desktop one, its title ending in "(phone)". Read the components'
small-screen branches first: on a phone the names and the way in differ (a
menu button before the item). A place that looks the same on both needs only
one. In `ac` mode a criterion about one of them shows that one.

## 3. Who sees each one

One user for every scenario is fine, and the default: the one whose data
shows the feature best. Switch users where the point is how it looks to
somebody else — the feature shows differently to an owner and a guest, an
admin and a plain user, somebody with data and somebody without; that is what
a demo often has to show, and since every scenario signs in by itself a
second user costs the person nothing. Not a different user per scenario for
its own sake.

`python3 $D/demo.py users` lists the users of the feature's database. Pick the
user whose data and role show each scenario; read the seed
(`supabase/seed.sql` or the project's seed script) or query the database when
the list alone does not say who is who. Never invent an address: one that does
not exist is refused, not created. When nobody in the database fits a
scenario, say so and say what user it needs — do not create one unasked.

## 4. The script (default and `live`)

Write it to `<tree>/.sclaude/local/demo/script.mjs` (a delta to
`delta.mjs`; both kept out of git), a
module whose default export is the demo:

```js
export default {
  title: "Event view: what owners and guests see",
  viewport: "desktop",            // the default; a scenario may set "phone" (live keeps the window's size)
  scenarios: [
    {
      title: "AC1. The owner sees every field",
      as: "owner@example.com",    // a user from demo.py users
      path: "/events/42",         // where it starts, signed in
      shows: "What the scenario demonstrates, in a sentence or two.",
      look: ["what to watch for", "…"],
      why: "Why this case matters, and how it differs from the others.",
      async steps(d) {
        await d.say("The event as its owner opens it", d.page.getByRole("heading", { name: "Climbing" }));
        await d.click(d.page.getByRole("button", { name: "See as" }), {
          say: "Switch to how a guest sees it",
          look: "the address and the price disappear",
          why: "a guest must not see what only members may",
        });
        await d.check(d.page.getByText("Members only"), "The hidden fields are marked");
      },
    },
  ],
};
```

`d.page` is Playwright's page. The helpers put a caption (top of the page),
a ring and a cursor on the page before acting, note the step's time and
address, and wait for the target (10 s):

| helper | does |
|---|---|
| `d.say(text, target?)` | a caption, the target ringed |
| `d.click(target, text)` | clicks it |
| `d.fill(target, value, text)` | types the value into it |
| `d.select(target, value, text)` | picks an option of a `<select>` |
| `d.press(key, text)` | a key, e.g. `"Enter"` |
| `d.goto(path, text)` | another page of the feature |
| `d.check(target, text)` | marks ✓ when it is visible, ✗ when not; goes on either way |
| `d.wait(ms)` | a pause |

A target is a Playwright locator (or a CSS selector string). Prefer
`getByRole`, `getByLabel`, `getByText` with the names the components really
render — read them, do not guess; `.first()` where several match. `text` is a
line, or `{say, look, why}` — what happens, where to look, what it proves;
give `look` and `why` on the steps that carry the point, not on every click.
The scenario's `shows`, `look` and `why` open it as a card. A failed action
ends its scenario (the next one runs); a failed check does not.

A demo acts on the feature's own local database as a person would: it may
create and change data there; it does not delete the seed's users or data
other scenarios need.

## 4a. A delta

`python3 $D/demo.py last` names the last full demo — the commit it shows and
its script. Read what changed since: `git diff <its head>` and `git log <its
head>..HEAD`, and the old script. Decide first whether any of it changes what
a user sees or does; if none does, say so in a line and stop.

Otherwise write a script with `kind: "delta"` and `change:` — the change for
the user in one sentence, in business terms ("A guest now sees the price, not
"price hidden""), the way a release note says it. Its scenarios show only the
places that changed, each one's `shows` saying what it was before and what it
is now, desktop and phone where the change differs between them. A delta is
recorded before the full demo that follows it: played, it goes to the
feature's topic, and into the issue with that full demo.

## 4b. A part's demo, and the whole feature from the parts

A feature sclaude builds in parts is shown part by part: between two parts
sclaude starts a session with this skill (`SCLAUDE_DEMO_PART`, set by
`demo_part` in sclaude) that records only what the part just built added — a
delta measured from where the part began, not from a full demo, so it does not
run `demo.py last`. The history keeps it with its `part`, the topic gets it as
`🧩 Part N: <change>`, and the feature's page lists it among the changes
before the first full demo.

`python3 $D/demo.py parts` lists each part's last such recording: the commit
it shows, what it added and its script (`none:` when there is none). Once
every part is built, the whole feature's script is written from those —
keep the scenarios that still show the feature, rewrite what a later part
changed, add what only the parts together show — rather than anew.

## 5. Playing it

```bash
python3 $D/demo.py play <tree>/.sclaude/local/demo/script.mjs [--live] [--feature F]
```

Run it with a long timeout (ten minutes) or in the background: it takes the
demo's length and more. Recorded, it prints a line per scenario (`done`, or what failed), then
`where:`, `link:` and `other:` for the demo's page, the way section 6 reads
them. In a session sclaude runs (`SCLAUDE_SESSION` is set) it then sends
the links and the scenarios' videos to the feature's Telegram topic (`sent:`)
— a full demo also deletes the topic's messages of the full demo before it
and of everything older (`telegram: N earlier message(s) deleted`), so the
topic holds the current demo and the deltas leading to it; Telegram lets a bot
delete nothing older than 48 hours, which stays — and posts them, with how each scenario went and the commit shown, as the
issue's demo comment, the earlier one deleted (`issue: posted on #N with K
video(s)`, or why not); anywhere else it says
`kept here:` and sends nothing — give the links in the answer, as always.
A recording with a scenario that did not play — not signed in, a step that
could not be done — says `not published:` and goes nowhere: the topic, the
issue and the feature's page keep the demo they had, and `stale` measures from
that one. Fix the script and play it again; never report such a run's links as
sent.

Every recording goes into the feature's history, and the feature's demo page
— `/__sclaude/demo/<feature>/`, the address `link:` gives — keeps them all,
as versions: a full demo with the deltas recorded before it. On top the
current version, marked CURRENT, with since when, what changed in it and its
videos; below, every earlier version, newest first, marked OUTDATED with the
time it was the current one (from — to), its deltas and its videos folded. The stage is the step's in a
session sclaude runs (`2-code`), or the one sclaude names (`preview`,
`epilogue`).

`python3 $D/demo.py stale` says whether the product's code changed since the
last full demo recorded in the tree: exit 0 with `stale:` or `none:` — record one;
exit 1 with `fresh:` — the demo shows the code as it is. It compares the files
as they are with the files the demo played — committed or not, new ones
included, unless `.gitignore` names them; docs (`*.md`) and `.sclaude/` do not
count. `python3 $D/demo.py replay` plays the last demo's
script again as it is, with no model — what sclaude falls back to before the
QA when it cannot start a session to write the demo again.

`python3 $D/demo.py keep "<why>"` carries the last full demo on to the code as
it is, when the code changed since but nothing a user sees or does did: no
recording, nothing published, and `stale` says `fresh` again; the feature's
page says the demo is still current, and why. It is for the same question a
delta asks first — use it instead of recording the same thing twice.

In a feature's tree, `play` keeps how far the recording got in the
feature's state (`demo_progress`: the scenario of how many, the step) from
the player's `progress:` lines, and clears it at the end; Claude Code's
status line shows it while the call runs, and sclaude's terminal while it
records a demo again. Nothing to do for it.

With `SCLAUDE_DEMO_HOLD=1`, which sclaude sets when it records a demo again
with nobody watching, `play` records into its own folder and sends nothing
(`held:`); the feature's page keeps showing the demo it had — check the
recording by its `demo.json`. Once the session is over sclaude publishes the
last delta and the last full recording it made, each with
`python3 $D/demo.py publish <id>`, so a try that needed fixing never reaches the
page, the topic or the issue; after `keep` it publishes nothing.

Before giving the link, read `<tree>/.sclaude/local/demo/<id>/demo.json`: a
scenario with `error`, or a step with `error` or `ok: false` that should have
passed, is a script to fix (a name that differs, a wait too short) — fix it
and play again, twice at most. A check that fails because the feature does
not do what it should is a finding: keep it, and say so.

The answer: one line where the link is for, the link, then a line per
scenario — its title and the user — and what did not work, if anything. End
with the `other:` link for the other place.

Live, `play --live` brings chrome-debug forward and returns at once: the
demo plays in its windows, and the player stays until they are closed. Say
that ⏸ on the page hands it over (▶ goes on), ⏭ goes to the next scenario,
and ⏹ ends it for good, leaving the windows signed in.

## 6. `links`: a link per scenario

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
beats the guess. `play` reads the same.

The answer: one line where the links are for (from `where:`), then the
scenarios, numbered, each:

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
person's feet. With `open` they are asked for, and opened where that cannot
happen:

```bash
python3 $D/demo.py open <email> <path> [<email> <path>]... [--feature F]
```

Every scenario's user and page, in the scenarios' order. Each user gets a
window of their own — a browser context with cookies of its own — holding
their scenarios as tabs; the window the person and the sessions work in
keeps its session. The windows of this feature's previous `open` are closed
first. The tabs are the laptop's links, whatever `where:` said: chrome-debug
runs on the laptop. Add one line saying which windows opened (`window:`
lines) and pass on `warn:` and `failed:`.

Not covered: a phone without Tailscale, through the bot's Mini App — there a
feature opens from its card in Telegram, not from a link.
