# Contributing to sclaude

sclaude is installed as it is by every team that uses it: nobody forks it to
customise it. What is a team's own lives in its product's repository; what
everybody shares reaches everybody through this repository's pull requests.
This page is the short way into both.

## Connecting a product

1. Install sclaude ([README, Installation](README.md#installation)) and run
   `sclaude doctor`.
2. In the product's repository, run `sclaude new`. Without a
   `.sclaude/config.json` it offers to write one: it reads the tests from
   `package.json`, the manuals and migrations from the layout, and the board
   from the repository's GitHub project, and shows everything before writing.
3. Read what it proposes against
   [`sclaude/config.example.json`](sclaude/config.example.json), which explains
   every key, and commit the file. `sclaude config` changes it later, with the
   same explanations beside your values.

Every section is optional, and nothing is guessed at run time: a product with
no test suite simply has no test gate, and sclaude says so where it would have
acted. [The environment it is built for](README.md#the-environment-it-is-built-for)
lists what each part of the cycle needs.

## What lives in a product's `.sclaude/`

| path | what | committed |
|---|---|---|
| `config.json` | the product: its checks, environments, database, board, maintainers, where its metrics go | yes |
| `team/policy.json`, `team/prompts/<step>.md` | the team's rules for sessions and its additions to sclaude's prompts, kept by the product's `maintainers` | yes |
| `people/<name>/…` | the same, for one developer | yes |
| `local/` | what one machine keeps: a feature's working files, terminal recordings | never, and never deployed |

A team's rules, data and recordings stay in its product. Nothing about a
product is ever committed here.

## Proposing a change to sclaude

`MAINTAINERS` lists who commits sclaude straight to `main`; everybody else
proposes:

1. Commit your change in your sclaude checkout as usual.
2. Run `sclaude propose`. The commits move to a branch of their own,
   `dev/<name>`, and go out as a pull request — pushed here if you may push,
   otherwise through a fork `gh` makes for you once.

Your name is the part of your git email before the `@`, or
`git config --global sclaude.developer <name>`.

sclaude's sessions never change your checkout of this repository: a session
that finds a bug in sclaude fixes it in its feature's workshop, and sclaude
sends that the same way — a pull request for you, after checking it for your
product's details ([README, "When a session finds a bug in
sclaude"](README.md#who-changes-the-orchestrator)). A change you make by hand
is what `sclaude propose` is for.

## The rules of this repository

[CLAUDE.md](CLAUDE.md) holds them in full; it is what Claude Code sessions read,
and it is meant for people as much. The ones a first change meets:

- **English only**, in code, comments, prompts, output and commit messages,
  with three listed exceptions.
- **No product details.** No product names, numbers of issues or pull requests,
  paths, tables or infrastructure of any product. Describe a problem in the
  orchestrator's own terms.
- **Commit messages**: a Conventional Commits subject, a body that says *why*,
  and an unbroken trailer block. `githooks/commit-msg` checks the trailers.
- **Strings coupled across files** are listed in `CLAUDE.md`; grep before you
  change one side.
- **`bin/sclaude` and `bin/keepawake` edit themselves while running**: keep
  their `{ … } exit` wrapping.

## Running the tests

Each file in `tests/` is standalone and exits non-zero on failure:

```bash
python3 tests/<name>.py
```

Before a commit, the tests that name a changed file, side by side:

```bash
tests/run --changed
```

Before a pull request, all of them (about two minutes):

```bash
tests/run
```

Shell files have no runner of their own: check them with `bash -n`.

When a change adds or changes something a user meets — a command, a key, a
switch, a behaviour — update [README.md](README.md) in the same pull request.
How a part works inside goes to [docs/sclaude.md](docs/sclaude.md) or
[docs/keepawake.md](docs/keepawake.md).

## Licence

sclaude is under the [MIT licence](LICENSE). By contributing you agree that
your contribution is published under it.
