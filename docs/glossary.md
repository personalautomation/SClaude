# Glossary

The words sclaude and its guides use, each in a line or two, with where to read
more.

**Acceptance criteria (AC)** — the numbered list (AC1, AC2…) step 1 ends with:
behaviours anyone can check on a deployment without reading the code. QA ticks
them in the issue. → [A feature, start to finish](sclaude-guide.md#a-feature-start-to-finish)

**The cycle** — the path of one feature: planning, development, the pull
request, the review, then the sync with main when needed, the epilogue and the
retrospective. The menu numbers them 1 to 7. → [The cycle](sclaude-guide.md#a-feature-start-to-finish)

**Step 1, planning** — Claude restates the issue, asks what it does not know and
writes the plan and its acceptance criteria. It cannot write code.

**Step 2, development** — a fresh session builds from the plan, checks it in a
browser, records a demo, and ends on your Accept and green local tests.

**Step 3, pull request** — a draft pull request with the criteria in it and the
product's manuals updated.

**Step 4, review** — the automatic review and the sessions that fix what it
finds, round by round until nothing is open; then the preview and QA.

**Step 5, sync with main** — only when the branch conflicts with main: main is
merged in, the conflict resolved and checked.

**Step 6, epilogue** — a short session that writes how the feature ended in a
*Current status* comment on its issue and every parent issue.

**Step 7, retrospective** — reads the feature's terminal recording and says what
went wrong, how to work better, and what sclaude could do better.

**Feature** — one issue taken through the cycle, in its own worktree with its
own branch, dev server, address and database.

**Worktree, tree** — the feature's own copy of the product, a git worktree
beside the main checkout (`<product>-<feature>`). Removed by `sclaude done`.

**Main checkout** — the product's own folder, on `main`. Its config is the one
read for every feature, and production is deployed from it.

**Gate** — a point the cycle does not pass until the product's tests are green:
before steps 2 and 4 close, on the preview, on production. A stage with no tests
has no gate. → [Quality gates](cycle.md#quality-gates-in-the-definition-of-done-sense)

**Regression, stages** — the product's checks, by stage: `local` on this
machine, `preview` and `prod` against the deployments, `manual` when only the
manuals changed, `smoke` the few vital paths. → [regression](config.md#regression)

**Preview** — the branch deployed to an address of its own after the review; its
tests run there, and it is what QA looks at.

**QA** — a person checking the preview against the acceptance criteria and
moving the issue to Done, or back. The `qa` setting decides who gives that word.
→ [qa](config.md#qa)

**Hand-off, hand-back** — QA's Done hands the pull request over for the merge:
marked ready, with a summary. A move back to In progress is a hand-back: QA's
comments go to a review session.

**Ship** — production after the merge; the `ship` setting decides whether it is
asked. → [ship](config.md#ship)

**Rollback** — production put back to the release before the feature when its
tests are red there, never over somebody else's release.
→ [Production rollback](cycle.md#production-rollback-that-refuses-to-trample-somebody-else)

**Production held** — production's tests were red and it was not rolled back:
the feature waits for a green run, a rollback or a return to step 4.

**Parts** — a feature too big for one go, built in parts within step 2; still one
issue, one plan, one pull request and one QA.
→ [A feature, start to finish](sclaude-guide.md#a-feature-start-to-finish)

**Review blocks** — a pull request too big for one review, read in blocks of
behaviours with their files. → [Review in blocks](config.md#review-in-blocks-reviewblocks)

**Review round, pass** — a pass is one run of the review; a round is a pass and
the session that fixes what it found.

**`[s]`** — in step 4, makes the next pass the last one that looks for new
findings (⏭ in the feature's topic).

**`[g]`** — in step 4, lets the rounds go on without asking: a failed pass runs
again, the fixes are checked, open findings go back to a session.

**Night, `/isleep`** — you have gone to sleep: sessions decide by their best
judgement instead of asking, keep a log of what they decided and give you a
summary in the morning. → [skills/isleep](tools.md#skillsisleep)

**Demo, `/sdemo`** — a video of the feature, played by a browser with captions,
one link with a video per scenario. → [skills/sdemo](tools.md#skillssdemo)

**Friction log** — where a step's session writes what got in its way, such as a
command the rules refused.

**Friction review** — after a step, a session that reads the friction log and
fixes sclaude, or loosens a rule that was in the way, on your approval.
→ [The tool repairs itself](cycle.md#the-tool-repairs-itself-and-says-what-a-machine-lacks)

**Deferred review** — the monthly review of the proposed rules that were put
off, offered by itself or run with `sclaude deferred`.

**Workshop** — a copy of sclaude's checkout where a session changes sclaude
itself; what it makes goes out on your word. `sclaude workshop` opens one to
work on sclaude with you. → [For a team](team.md)

**Process map** — the cycle drawn as a map: the printed one, and each feature's
own, with where it stands and its history played back.
→ [The decks and the process map](presentations/README.md)

**Metrics page** — the product's DORA keys and the cycle's own figures, at
`localhost:3000`. → [What is measured](cycle.md#what-is-measured)

**Proxy** — gives every feature its own address, `http://<feature>.localhost:3000`,
starting its dev server on a visit. → [bin/sclaude-proxy](tools.md#binsclaude-proxy)

**Phone access, Mini App** — off by default; turned on, the bot's menu opens as
an app inside Telegram, without Tailscale on the phone.
→ [The bot as an app](tools.md#the-bot-as-an-app-in-telegram-with-no-tailscale-on-the-phone)

**Topic** — the feature's own thread in the Telegram chat: its card, reports,
demos and questions.

**keepawake** — keeps the machine awake while there is work, so it can go on
from the phone, and runs the Telegram bot. → [bin/keepawake](tools.md#binkeepawake)

**Maintainers** — two lists. A product's `maintainers` keep its shared sclaude
rules (→ [maintainers](config.md#maintainers)); sclaude's `MAINTAINERS` may
commit sclaude itself straight to `main` (→ [For a team](team.md)).

**Team and personal rules** — `.sclaude/team/` holds the rules the product's
maintainers keep, `.sclaude/people/<name>/` one developer's own.
→ [Beyond config.json](config.md#beyond-configjson)

**Policy** — the commands a session may and may not run, in layers: sclaude's
own, an integration's, the team's, yours.

**Integration** — a service the product uses, such as Vercel or Supabase, which
turns on sclaude's rules and handling for it.

**Environment, protected** — one of the product's databases, named by its `.env`
file. A protected one holds real data, production: no feature is pointed there.
→ [environments](config.md#environments)

**devLogin** — opens a feature's browser already signed in, from the product's
sign-in route. → [Signing in: devLogin](config.md#signing-in-devlogin)

**doctor** — `sclaude doctor`: what the machine lacks and the command that fixes
each gap, with the product's own checks. → [Installation](setup.md#installation)

**Cycle record** — one line per finished feature in
`~/.claude/sclaude/cycles.jsonl`: its steps, times and outcome.
→ [What sclaude writes](sclaude-guide.md#what-sclaude-writes-and-where)
