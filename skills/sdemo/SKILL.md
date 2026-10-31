---
name: sdemo
description: A feature's demo, played for the person. `/sdemo` records a demo of the feature's main functionality — Playwright signs in as each scenario's user, clicks and types through it, with captions on the page saying what each step shows, where to look and why it matters — and gives one link to a page with a video per scenario, the steps beside it, and "take over" links that open any step's page signed in to go on by hand; `/sdemo ac` walks through the acceptance criteria instead; `/sdemo live` plays it in the laptop's chrome-debug with ⏸ to take over; `/sdemo links` gives plain signed-in links with what to check (`links open` opens them in chrome-debug). Links are for where the person is — the laptop's <feature>.localhost, or the tailnet's address on the phone. Use when the user invokes /sdemo, or asks to demo, show, try or check a feature.
argument-hint: "[ac] [live | links [open]] [feature] [what to show]"
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

What the person asked to be shown comes first and is never left out.

How it is shown:

- **default — a recorded demo**: Playwright plays the scenarios headless and
  records them; the person gets one link to a page with a video per
  scenario, its steps beside it (tap one to jump there), what each shows and
  why, and a **take over** link on every step that opens that page signed in
  as that user, to go on by hand. The link also goes to the feature's
  Telegram topic.
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

Write it to `<tree>/.sclaude/local/demo/script.mjs` (kept out of git), a
module whose default export is the demo:

```js
export default {
  title: "Event view: what owners and guests see",
  viewport: "desktop",            // or "phone", when the feature is a phone's (live keeps the window's size)
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

## 5. Playing it

```bash
python3 $D/demo.py play <tree>/.sclaude/local/demo/script.mjs [--live] [--feature F]
```

Run it with a long timeout (ten minutes) or in the background: it takes the
demo's length and more. Recorded, it prints a line per scenario (`done`, or what failed), then
`where:`, `link:` and `other:` for the demo's page, the way section 6 reads
them, and `sent:` when the link went to the feature's Telegram topic.

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
