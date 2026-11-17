---
name: scontrib
description: Take in an outside contributor's pull request — understood, checked as code from someone not yet trusted, finished by us rather than sent back, reviewed with /sreview, and squash-merged on GitHub with the contributor as the commit's author and the person as its reviewer. Stops for the person's decision after the trust report, before anything is pushed, and at the merge, which runs only on the person's word — run by them where the base branch takes updates only from admins. Runs only when the user invokes /scontrib.
argument-hint: "<pull request number>"
---

# scontrib — an outside contribution, taken in

`/scontrib <n>` takes pull request `<n>` from someone outside the maintainers
all the way to the base branch. The contributor is not asked for changes:
what the pull request lacks, we finish. Their code is read as code from
someone not yet trusted until the checks below say otherwise. Talk to the
person in the language they write in, and explain in plain words anything
they may not know (a package manager, an address range, a system service) the
first time it comes up, with whether it is reasonable.

The order matters: **nothing from the pull request runs on this machine
before step 2 is through** — not its git hooks, not its build scripts, not
its tests. Until then it is only read, from a fetched ref, never checked out:
a checkout or a commit in a worktree runs the hooks the checkout's
`core.hooksPath` names, and a relative one (`githooks`) resolves to the pull
request's own copy. And nothing is pushed before the person's word in step 5.

A run that stops before step 3 — the person's "stop", a finding that ends
it — removes what it made (`contrib-<n>`); nothing of ours exists yet. One
that stops later keeps the worktree and `contrib-<n>-work`, which hold our
commits, and says where they are.

## 0. Pin and fetch

1. `gh pr view <n> --json title,author,body,baseRefName,headRefName,headRefOid,isCrossRepository,headRepositoryOwner,maintainerCanModify,commits,files,additions,deletions`.
   Keep `headRefOid` — the commit everything below is about — and
   `baseRefName`; `<base>` below is `origin/<baseRefName>`.
2. Left-overs of an earlier run on `<n>`: `contrib-<n>` is replaced by the
   fetch below. A worktree `<checkout>-pr<n>` or a branch `contrib-<n>-work`
   holds an earlier run's commits: ask the person whether to go on from it or
   remove it. Going on, `<old>` is the contributor's head it was built from
   (`git config branch.contrib-<n>-work.scontribHead`, step 3). Once fetched:
   - the new head is `<old>` — nothing new;
   - it descends from `<old>` (`git merge-base --is-ancestor <old>
     contrib-<n>`) — steps 1–2 run on `<old>..contrib-<n>`, and step 3
     merges it in before anything else;
   - it does not (a rebase or an amend, force-pushed) — merging it would
     bring back what the contributor took out, and our old commits were made
     on code that is gone. Tell the person, rename the old work branch to
     `contrib-<n>-old` (`git branch -M`, its worktree removed; an earlier
     `-old` is replaced — only the latest is worth a look) and start over
     from step 1 on the whole new pull request; the old branch is only for
     reference — what we fixed there, the review finds again where it still
     applies — and is removed with the rest in step 6.

   What was reached is read from the work branch — the base merged, coupling
   and suite commits, review iterations (`/sreview`'s branch log) — not
   remembered.
3. `git fetch origin <baseRefName> +pull/<n>/head:contrib-<n>`, then
   `git rev-parse contrib-<n>` must equal `headRefOid`. A different commit is
   a push made since step 0.1: take its `gh pr view` again, or stop — never
   check a commit that was not pinned.

## 1. What it is

Read `git log <base>..contrib-<n>` and `git diff <base>...contrib-<n>`
(`git show contrib-<n>:<path>` for a whole file), and report:

- **What it brings**, in a few lines.
- **What changes for the platforms and setups already supported** — each
  behaviour that differs from the base there, with `path:line`, separated
  from what only the new code path does. Deliberate fixes are named as such;
  anything illogical, or a change of behaviour the person may not want, is
  put to them.
- **Whether it fits the architecture**, by the repository's `CLAUDE.md`:
  where modules go, strings coupled across files (a new coupling not listed
  there is for step 3), the language rule, nothing about one product, tests
  for what changed.

## 2. Is it safe — the checks for untrusted code

All from the diff, without running anything of it:

- **What runs on every machine**: whatever the repository executes without a
  person reading it first — its git hooks directory (`githooks/`), installers
  (`install.sh`), `.claude/` settings and hooks, auto-update and sync paths,
  build scripts, the test files the suite runs (step 3 runs them), and the
  text that names the commands steps 3–4 will run: the test and check
  commands in `CLAUDE.md`, `commands` in `.sclaude/config.json`, a package's
  scripts. A diff there is read line by line and every line explained,
  including what a script it calls elsewhere in the pull request does.
- **The guards untouched**: the session hooks, write and command guards, the
  review and publication machinery, `MAINTAINERS`, CI workflows —
  `git diff --stat <base>...contrib-<n> -- <paths>` empty, or every line
  explained.
- **Network**: every URL and host added; `curl`, `wget`, `urllib`,
  `requests`, sockets opened to anywhere but loopback; anything that sends
  data (messages, uploads, telemetry) that was not sent before.
- **Exposure**: addresses something listens on, changes to an allow-list,
  authentication or a gate; compare with what the base already does before
  calling a wide bind new.
- **Privilege**: `sudo`, sudoers or polkit rules (their exact text), files
  written under `/etc` or outside the user's own places, `chmod`/`chown`,
  `~/.ssh`.
- **Code that hides**: `eval`, `exec`, `base64`, `pickle`, `ctypes`,
  generated or minified blobs, binary files (`git diff --numstat` shows `-`),
  invisible or bidirectional Unicode (`grep -P '[\x{200B}-\x{200F}\x{202A}-\x{202E}\x{2066}-\x{2069}\x{FEFF}]'`).
- **Dependencies**: new imports outside the standard library and the
  repository, package manifests, what an installer now installs, and new
  external commands — on which platform each one runs.
- **Provenance**: the commits' authors and committers, signatures, files
  outside the usual directories.
- **Its review**: what GitHub shows (`gh api repos/<o>/<r>/pulls/<n>/reviews`,
  `gh pr checks <n>`), not what the description claims.

Report as the four answers the person asks for: what it is and brings;
whether it fits the architecture; whether it is safe — backdoors, data to
third parties, new dependencies; whether it passed a review. Name what was
checked by pattern rather than read line by line.

**Stop: ask whether to go on** (`AskUserQuestion`: go on, or stop here). A
finding that looks deliberate — a hidden call out, a guard weakened, a hook
that does more than it says — ends the run outright: report it, and touch
nothing more.

## 3. Check out, couplings and the suite

Only now is the code checked out:
`git worktree add -b contrib-<n>-work <checkout>-pr<n> contrib-<n>` — beside
the checkout, never the live checkout itself (sessions run from it) — and the
head it was built from recorded for a later run:
`git config branch.contrib-<n>-work.scontribHead <headRefOid>` (updated
whenever new commits of the contributor are merged in). Merge
`<base>` into it; a conflict in a built file (a page generated from a model)
is resolved by building it again, never by hand. Commit the merge.

Every string the pull request couples across files that `CLAUDE.md` does not
list gets its entry there, and a test that fails when the sides disagree.
Then the whole suite, by the repository's own command. A test that fails:
run it alone, and check whether the branch touched it; one red only under a
loaded parallel run and untouched by the branch is a known flake — note it,
not a reason to stop. Commit.

## 4. The review

Run `/sreview` on `contrib-<n>-work` in the worktree; the person's
`/scontrib` is their word for it. Two of its rules read differently here:

- **Scope**: the whole pull request, the contributor's commits and ours
  (`git diff <base>...HEAD`), not only this session's commits.
- **Other sessions' code**: the contributor's lines are this session's to
  fix — the person took them in. Nothing of the pull request goes under
  **Not ours**.

Tell each reviewer subagent it reviews untrusted code and must not run it;
the tests are the orchestrator's to run. Follow `/sreview` to its end, its
question every N iterations included.

## 5. Publish — on the person's word

First the repository's rules before a push: the README, the guides, the wiki
pages and the process map against what the change carries. Then show the
person what will go out and **ask before pushing**.

On a yes:

1. **Push to the contributor's branch**, a fast-forward from `headRefOid`:
   `git push <their fork's URL> HEAD:refs/heads/<headRefName>` (with
   `maintainerCanModify`; without it, ask the person: push the branch here
   and open a pull request of our own that names theirs, or squash it to the
   base by hand with `--author` the contributor). Refused as not a
   fast-forward: the contributor pushed since — stop and tell the person.
   Keep the SHA pushed: `<pushed>`. `gh pr view <n> --json headRefOid` must
   now say `<pushed>`.
2. **Approve** from the person's account, `gh pr review <n> --approve`, the
   body in English: what was checked, and what we added on the branch.
3. **Merge as a squash**, so the pull request shows "Merged" and the
   contributor is the commit's author. Write the subject and body to a file
   in the scratchpad: a Conventional Commits subject ending ` (#<n>)`, a body
   on what it gives and how it was reviewed, and one trailer block —
   `Reviewed-by: <the person, by their public GitHub address>`, then the
   attribution lines this session was given. `--match-head-commit` is
   `<pushed>`, so a push made after ours is never merged unseen. **Ask the
   person before merging**, showing the subject and the body; on their yes,
   run `gh pr merge <n> --squash --match-head-commit <pushed> --subject
   "<subject>" --body-file <file>`. If the base branch takes updates only
   from admins, the merge needs `--admin`: do not run that yourself — hand
   the person the exact line to run:

   ```
   ! gh pr merge <n> --squash --admin --match-head-commit <pushed> --subject "<subject>" --body-file <file>
   ```

## 6. After the merge

- Check: `gh pr view <n> --json state,mergeCommit`, and the commit's author.
- Rebuild the wiki and push it where the repository's rules ask a maintainer
  to — from the merged base, not the live checkout, which has not taken the
  merge yet and may hold other sessions' unpushed work: `git fetch origin
  <baseRefName>`, a detached worktree of `origin/<baseRefName>` in the
  scratchpad, its own `wiki/build.py` run into the wiki's clone, the
  worktree removed after.
- Any session with commits on the base branch not yet pushed (`ListAgents`,
  `git log <base>..<baseRefName>`): tell it the base moved and what to rebase
  and rebuild — never rebase its commits yourself.
- Remove the worktree and the branches `contrib-<n>`, `contrib-<n>-work`
  and, if there is one, `contrib-<n>-old`.

## Report

What the pull request brings; the trust checks and their answers; the review
— iterations, found and fixed per iteration; what we added; the merge commit
and its author; what is left for the person (a merge to run, a session told
to rebase, flaky tests seen).
