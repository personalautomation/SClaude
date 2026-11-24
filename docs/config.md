# The product's config, key by key

Everything sclaude knows about a product is in one file in the product's
repository, `.sclaude/config.json`, committed with the code. This page explains
every key in it: what it does, the values it takes and what happens when it is
left out. The same explanations come with the example file,
[`sclaude/config.example.json`](../sclaude/config.example.json), and
`sclaude config` shows them beside your values.

## How the file works

**Writing it.** `sclaude new` in a repository without the file offers to write
one: it reads the tests from `package.json`, the manuals and migrations from the
layout, the environments from the `.env` files and the board from the
repository's GitHub project, and shows everything before it writes. What it
could not work out you add by hand, with this page beside you.

**Every key is optional, and nothing is guessed.** What the file leaves out is
not done: without `regression` there is no test gate, without `manuals` step 1
gets no table of contents, without a way to deploy production is never offered.
sclaude says so where it would have acted. A default that fits one product
would be a wrong guess about the next, so the only defaults are the ones named
below for each key.

**The team's file and your own choices.** The committed file is what the team
recommends. The keys with a fixed set of values — those in
[Choices](#choices-you-can-make-for-your-machine) — can also be set from
`sclaude config` or the bot's 🧩 menu, and such a choice is yours alone: it is
kept in `.sclaude/local/config.json` beside the committed file, outside git, and
wins over the committed value key by key. Setting a choice back to the team's
value removes it from there. So your `ship: auto` is not everybody's, and the
committed file in the main checkout stays what origin holds. Do not edit the
committed file by hand without committing: production stops until the main
checkout's copy is what origin holds, and says where the two differ.

**Which copy is read.** The main checkout's file is read for every feature, so
a choice made today applies to features begun before it. A key the main
checkout lacks is taken from the feature's own copy, so a feature whose branch
adds a key can use it before the branch merges. The commands under `commands`
and `database.local.cli` are read from the feature's copy first when its branch
changed them, since they describe the branch's code. `maintainers`,
`environments` and `devLogin` are read as `origin/main` has them, never as a
feature's branch does: a branch cannot make itself a maintainer or point itself
at production.

**Unknown keys.** `sclaude config` lists a key sclaude does not read as such,
so a misspelt key is visible rather than silently ignored.

## Choices you can make for your machine

Each of these takes one word from a fixed list. Any other word, or none, means
the default.

| key | values | default |
|---|---|---|
| `review` | `github`, `github-local`, `local`, `off` | `github` |
| `qa` | `github`, `both`, `auto`, `auto-own` | `github` |
| `merge` | `github`, `both`, `auto` | `both` |
| `ship` | `ask`, `auto`, `off` | `ask` |
| `previewRegression` | `full`, `smoke`, `none` | `full` |
| `prodRegression` | `full`, `smoke`, `none` | `full` |
| `demo` | `on`, `off` | `on` |
| `demoVoice` | `on`, `off` | `on` |
| `simplify` | `on`, `off` | `on` |
| `partAccept` | `whole`, `each` | `whole` |
| `sleep_mode` | `auto`, `on`, `off` | `auto` |
| `metricsTeam` | `real`, `demo` | `real` |

### review

Where the pull request's review runs at step 4.

- `github` — the review workflow in GitHub Actions, on the repository's runner
  minutes and its Claude token. When its Claude job cannot run (the
  subscription's limit, no Actions minutes, a runner without network), step 4
  stops and says why.
- `github-local` — the same, and when the workflow cannot run the feature moves
  to the review on this machine for the rest of its life, and other features
  for a while after.
- `local` — sclaude runs the same review on this machine, under the Claude
  account logged in here, and posts its findings as threads on the pull
  request, as the workflow would. It costs your Claude usage and no Actions
  minutes. Nothing on Actions counts in this mode: what the project's CI
  checked must be in the `local` stage of `regression`, which runs on this
  machine before steps 2 and 4 close. Set from `sclaude config`, `local` also
  switches the repository's Actions workflows off (they would fail on every
  push and mail about it), and going back to `github` switches on again the
  ones it switched off.
- `off` — no review; step 4 waits only for the checks and people's comments.

With `local` and `off` the pull request is opened with the `no-review` label,
the workflow's own switch, so the workflow skips itself at no cost. What the
review workflow has to write for sclaude to read it is in
[Setting up](setup.md#what-sclaude-reads-from-your-review-workflow).

### qa

Who accepts the feature once the preview's regression is green.

- `github` — a person checks the preview against the acceptance criteria and
  moves the issue to the board's Done column; sclaude waits.
- `both` — the same, or `a` pressed in sclaude's wait: sclaude ticks every
  acceptance criterion in the issue and moves it to Done itself.
- `auto` — sclaude does that at once and waits for nobody: the preview's
  regression is the only check.
- `auto-own` — `auto` when the issue was opened by the person working on it
  (the GitHub account sclaude runs as), `github` for anybody else's issue, so
  its author checks what they asked for. When GitHub does not say who opened
  it, sclaude waits for a person.

An issue sclaude accepted gets a comment saying so, so the board's history does
not read as a person's look. QA is waited for only when `board.columns.done` is
set.

### merge

Who merges the pull request once QA passed.

- `github` — somebody merges it on GitHub; sclaude waits.
- `both` — the same, or sclaude asks, and `m` pressed in its wait merges from
  here.
- `auto` — sclaude merges as soon as QA passed and GitHub allows it, and carries
  on.

Never before QA: with `qa: github`, `merge: auto` still waits for the board.

### ship

Whether the merge goes on to production.

- `ask` — after the merge sclaude asks "Ship to production?".
- `auto` — shipped without the question. It is still asked when QA or a check
  was passed over on the way, or when other features' code merged since the
  last ship would go out with it.
- `off` — sclaude never deploys production; the issue closes as merged and
  accepted, and shipping is done by hand.

### previewRegression and prodRegression

What the regression against the preview (before QA) and against production
(after the ship) runs.

- `full` — the stage's whole list in `regression.preview` or `regression.prod`.
- `smoke` — only `regression.smoke`, the product's few vital paths; the whole
  list where the product declares no smoke list.
- `none` — no regression at that stage, and no gate.

### demo

Whether the feature is shown as video (the `/sdemo` skill).

- `on` — step 2 records a demo before its Accept question. When the code
  changed since, it is recorded again: before QA where a person does QA, or
  before the last epilogue with `qa: auto` (or `auto-own` on your own issue).
- `off` — no demo videos anywhere in the cycle; the report and the criteria are
  the check.

### simplify

Whether Claude Code's `/simplify` cleans the feature's code: reuse, simpler
code, efficiency. The review in step 4 looks for bugs, not for this.

- `on` — step 2 runs `/simplify` before its Accept question; a feature built in
  parts runs it in each part's session, over that part. Step 4 runs it once
  more, over the whole pull request, in a polish round once the review has
  nothing left open.
- `off` — no `/simplify`, and no polish round.

### demoVoice

Whether a recorded demo is spoken.

- `on` — each step's caption is read aloud on the video, in English, by a speech
  model that runs on this machine's processor; it is fetched once, about
  350 MB.
- `off` — silent videos.

### partAccept

For a big feature built in parts
([Big features in parts](sclaude-guide.md#a-feature-start-to-finish)).

- `whole` — you see it once, when every part is built, and accept it then.
- `each` — every part's session also ends on its demo and the Accept question,
  and the whole is accepted again at the end.

Either way the accepted parts become one pull request.

### sleep_mode

When step 4's review goes on by itself, as `[g]` does: no question after a
review pass, a failed pass runs again, the fixes are checked, open findings go
back to a session.

- `auto` — while your `/isleep` night over every session is on (not an
  `/isleep here` one), and asking again once you are back.
- `on` — always.
- `off` — only where `[g]` is ticked by hand.

A `[g]` set by hand on a feature, on or off, wins over this.

### metricsTeam

Who the metrics page compares.

- `real` — the people whose work is in the records.
- `demo` — three generated teammates beside you, drawn from your real figures,
  for showing the page with a team. Generated data: never present it as
  anybody's real work.

## Tests: commands, regression, testRunner

### commands

The command behind each part of the regression, by a name you choose:

```json
"commands": {
  "typecheck": "npm run typecheck",
  "lint": "npm run lint",
  "build": "npm run build",
  "e2e": "npm run test:e2e",
  "smoke": "npm run test:e2e -- --grep @smoke",
  "dev": "npm run dev"
}
```

The names appear beside durations in the summary and in "failed on …". Three
names mean something to sclaude:

- `e2e` and `smoke` are browser suites: against a deployed stage they run with
  `E2E_BASE_URL` set to the deployment's address, so one command serves the
  local stage and the deployed ones.
- `dev` is not a regression part: it starts a feature's dev server, told its
  port in `PORT`. Absent, `npm run dev`.
- `e2e:server` (written `"e2e:server": "…"`) serves the built app on the
  feature's port during the local e2e, in place of the dev server, when the
  same run built it (`build` is in the `local` list). It is read from the
  feature's own copy only, since whether a build can stand in for the dev
  server is a fact about the branch's code. Absent, e2e runs against the dev
  server.

Every part runs with `SCLAUDE_DEV` set to the developer's name, so a suite that
creates test data on a shared database can mark it and clean up only its own.

### regression

Which parts each stage runs, in order:

```json
"regression": {
  "local": ["typecheck", "lint", "build", "e2e"],
  "manual": ["typecheck", "lint"],
  "preview": ["e2e"],
  "prod": ["smoke"],
  "smoke": ["smoke"]
}
```

- `local` closes step 2 and step 4 against this machine's dev server.
- `manual` is what the end of the review runs instead of `local` when nothing
  but the manuals changed since the last green local run — checks that read the
  code, without the dev server and the database. Absent or empty, the full
  `local` list runs.
- `preview` runs against the preview deployment before QA, `prod` against
  production after the ship; they usually hold only what a browser can see.
- `smoke` is what a deployed stage runs instead of its own list where
  `previewRegression` or `prodRegression` says `smoke`.

A stage with no list has no gate. A part named here with no command in
`commands` stops the run instead of being skipped: a suite that quietly drops a
check reports green on work it never did. A feature's branch may add parts to a
stage's list; it cannot drop one the main checkout's list has.

### testRunner

The browser suite's runner, which tells the sessions how to drive a touch swipe
in tests. Absent, `playwright`.

## Dependencies: deps

How the product's dependencies install:

```json
"deps": {
  "dir": "node_modules",
  "lockfile": "package-lock.json",
  "install": "npm install",
  "ci": "npm ci",
  "cache": ".next/dev"
}
```

- `dir` — the folder they go to. A new feature hard-links the main checkout's
  folder, so it starts in seconds.
- `lockfile` — the file that pins them. When it changed, sclaude installs.
- `install` — the command that installs in place; `ci` — the one that installs
  from scratch.
- `cache` — a folder their old versions leave behind, removed with them; `""`
  for none.

Absent, npm's values above. `dir` or `lockfile` set to `""` means sclaude
handles no dependencies.

## Hosting: deploy

How the product is put on hosting:

```json
"deploy": {
  "preview": "vercel deploy",
  "prod": "vercel deploy --prod"
}
```

- `preview` runs in the feature's tree; the last address it prints is the
  preview's.
- `prod` runs in the main checkout once it is up to date with main.

Absent, Vercel's commands where the product uses Vercel (named in the team's
`integrations`, below, or a `.vercel` link in the repository), and none
otherwise: the preview stage then fails at once naming the missing key, and
production is never offered, as with `ship: off`. A rollback of production is
known for Vercel alone.

## Environments: environments, envLink, envKeys, buildCache

### environments

The product's databases, each the `.env` file that holds its settings, relative
to the repository's root (`~` allowed):

```json
"environments": {
  "localdb": {"env": ".env.localdb"},
  "dev": {"env": ".env.dev"},
  "preview": {"env": ".env.preview", "deployed": true},
  "prod": {"env": ".env.prod", "protected": true, "siteUrl": "https://example.com"}
}
```

The names are yours. Each developer's machine is asked once which environment
it works against, and remembers the answer
([Environments and databases](sclaude-guide.md#environments-and-databases)).
Credentials stay in the `.env` files, never in this one.

- `env` — the file. An entry without one is ignored.
- `protected` — real data: no feature is pointed there and no session may
  switch a tree to it. The protected one is production.
- `siteUrl` — where production answers; the production regression runs
  against it. An environment whose `siteUrl` is not on localhost is never run
  against locally. With several protected entries, the one on `https` is
  production.
- `deployed` — one with no fixed address, such as previews, which a local dev
  server does not run against.

### envLink

The file in a tree that your code loads its settings from, and that sclaude
points at the chosen environment's `.env` file. A plain file name. Absent,
`.env.local`.

### envKeys

The names of the keys sclaude reads from the `.env` files, where yours differ:

```json
"envKeys": {
  "supabaseUrl": "NEXT_PUBLIC_SUPABASE_URL",
  "database": "POSTGRES_URL_NON_POOLING",
  "secretKey": "SUPABASE_SECRET_KEY"
}
```

- `supabaseUrl` — the Supabase project's address, by which sclaude links the
  Supabase command line to the environment's project.
- `database` — the database's address, for a production rollback and for
  signing in (`devLogin`). A rollback never prints it.
- `secretKey` — the service key `devLogin` uses.

Absent, the names above.

### buildCache

The folders in which a build keeps the settings it was made with, removed when a
tree moves to another environment so the next build does not use the old
database's settings. Absent, `[".next"]`; `[]` for none.

## Database: database

Everything about migrations; leave it out if the product has none.

```json
"database": {
  "migrations": "db/migrations",
  "schemaFile": "db/schema.sql",
  "historyTable": "schema_migrations",
  "promote": "npm run db:promote",
  "applyPreview": "npm run db:preview",
  "schemaDump": "npm run db:schema"
}
```

- `migrations` — the folder of migration files. Without it, nothing is promoted
  or reverted.
- `schemaFile` — the schema snapshot kept in the repository.
- `historyTable` — where the migration tool records what it has applied. A
  reverted migration's row is deleted from it, or the next promote refuses.
  Name it only if you know it: a guessed table that a rollback deletes from is
  worse than a row left behind.
- `promote` — applies the migrations to production after the ship. Sessions
  are never allowed to run it themselves.
- `applyPreview` — applies the branch's migrations to the preview's database
  before its regression. Without it the preview runs on the schema it has.
- `schemaDump` — writes the schema file again after a rollback.

### database.local

Gives every feature on the local environment a Supabase stack of its own in
Docker, removed with the feature:

```json
"local": {
  "environment": "localdb",
  "exclude": ["studio", "imgproxy"],
  "setup": "npm run seed",
  "env": {
    "NEXT_PUBLIC_SUPABASE_URL": "API_URL",
    "DATABASE_URL": "DB_URL"
  }
}
```

- `environment` — the name, in `environments`, of the local one. Without it
  features share the local database.
- `exclude` — the containers a feature does not need.
- `setup` — the command that fills a new stack. Without it the stack starts
  empty.
- `env` — each of your variables, mapped to the key of
  `supabase status -o env` that fills it in the feature's settings.
- `cli` — how the Supabase command line is run. Absent, `npx --yes supabase`.
- `copyFromMain` — `true` fills a new stack with a copy of the main local
  database's data instead of running `setup`, when that database is up.
- `teardown` — a command run before a removed feature's stack goes, with its
  settings loaded and `SCLAUDE_DB_FILLED` set to when it was filled: for what
  the database owned outside itself.
- `sweep` — a command run in the main checkout when no feature is in progress
  and no removed feature's stack is left on the machine, for five minutes at
  most: for what the local databases left outside themselves that a teardown
  could not tell was its own.

`sclaude dev --rebuild-db` resets a feature's stack and fills it the same way
again.

## Signing in: devLogin

Opens a feature's browser signed in, with one click, from the list at
`localhost:3000`, the bot's Mini App and `/sdemo`'s links:

```json
"devLogin": {"path": "/auth/confirm"}
```

`path` is the product's route for email sign-in links, the one that takes
`token_hash`, `type` and `next` and verifies them. Without it there is no
one-click sign-in. Who you are signed in as is each developer's own and never
committed: the first line of `~/.claude/sclaude/dev-login`, else your git
`user.email`. Never on a protected environment.

## The board: board

The repository's GitHub project board:

```json
"board": {
  "columns": {"backlog": "Backlog", "progress": "In progress", "qa": "In QA", "done": "Done"},
  "dates": {"start": "Start date", "end": "Target date"},
  "issue": {"label": "Dev", "type": "Feature"}
}
```

- `columns` — the column a started feature leaves (`backlog`) and enters
  (`progress`), where it goes once the preview is green (`qa`) and where QA
  passes it (`done`). Names are compared ignoring case and spaces. Without
  `done`, QA is not waited for on the board. In progress and Backlog are also
  how QA hands a feature back.
- `dates` — the issue's date fields filled when the feature starts and ends.
- `issue` — the label and the type a new issue gets.

Every key is optional: a column not named is a move not made.

## Review in blocks: reviewBlocks

A pull request too big for one review is read in blocks, each a group of
behaviours with the files that carry them:

```json
"reviewBlocks": {"from": 5000, "size": 3000}
```

- `from` — the changed lines (generated files left out) past which it is cut.
  Absent, 5000.
- `size` — the lines a block holds at most; a block that grew past it by its
  next whole read is split first. Absent, 3000.

## People, records and the machine

### manuals

The pages that describe the product as a person sees it:

```json
"manuals": [{"path": "docs/manual/billing.md", "what": "plans, invoices and refunds"}]
```

Step 1 gets their table of contents before it guesses at a feature's scope;
step 3 updates them in the same pull request as the feature. Without it, there
is neither, and no `manual` short regression.

### maintainers

The git addresses of the people who keep the product's shared sclaude rules in
`.sclaude/team/`:

```json
"maintainers": ["lead@example.com"]
```

Everybody else's sessions put their rules in `.sclaude/people/<name>/`, and a
maintainer lifts a rule from there into `team/`. Absent or empty, everybody is
a maintainer, which is what a product with one developer wants.

### metrics

A git repository of the team's own where each developer's cycle records of this
product are published, one `<developer>.jsonl` per person, for the metrics
page:

```json
"metrics": "git@github.com:your-team/sclaude-metrics.git"
```

Only this product's records go there. Absent, the records stay on the
developer's machine.

### doctor

What the product asks of a developer's machine beyond what sclaude checks:

```json
"doctor": [{"what": "Stripe CLI", "check": "stripe --version", "fix": "brew install stripe/stripe-cli/stripe"}]
```

Each `check` runs in the product's root; `sclaude doctor` shows ✓ when it
succeeds, or ! with its last line and the `fix` to run. These are warnings
only.

## Beyond config.json

A few settings live elsewhere, because they are not the product's description.

**The team's rules**, `.sclaude/team/policy.json`, committed and kept by the
maintainers ([For a team](team.md)):

- `integrations` — the services the product uses, such as `["vercel",
  "supabase"]`. Each turns on sclaude's preset rules for that service and what
  sclaude does with it, such as deploying through Vercel. Absent, they are
  recognised from the repository.
- `deny` and `allow` — commands a session may not run, or may run although an
  integration's preset forbids them, each with its reason
  (`{"command": "npm run db:promote", "why": "…"}`); `steps` holds the same per
  step. sclaude's own rules cannot be lifted.

**One developer's rules**, `.sclaude/people/<name>/policy.json`, the same
shape: they add bans and permissions of their own and lift nothing the team
bans.

**Extra instructions for a step**, `.sclaude/team/prompts/<step>.md` and
`.sclaude/people/<name>/prompts/<step>.md`, appended after sclaude's own prompt
for that step.

**Your machine's settings**, in the git config of sclaude's checkout, asked by
the installer ([Installation](setup.md#installation)) and shown by
`sclaude doctor`:

| setting | values | what it decides |
|---|---|---|
| `sclaude.developer` | your name | who you are to sclaude: your branches, your rules folder, your records. Absent, the part of your git email before the `@` |
| `sclaude.update` | `auto`, `notify`, `off` | whether sclaude takes its latest version at every start, says what is new for `sclaude update`, or never looks. Unset, it asks at the next start |
| `sclaude.contribute` | `send`, `ask`, `off` | whether a fix a session made to sclaude goes out unasked, on your yes, or no session changes sclaude here at all. Unset, `ask` |
| `sclaude.leaks` | `ask`, `auto`, `off` | whether such a fix that may name your product goes out only on your send after you see the lines, or without the question (`auto`). `off` asks, as `ask` does. Unset, `ask` |

Environment variables that change one run are listed in
[Switches](sclaude-guide.md#switches).
