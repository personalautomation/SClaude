The feature "<feature>" is done and I've accepted it. Close it out as a pull request.

Work through the `/pr` skill — invoke it. It differs from its usual course because the orchestrator has already done part of the work:

- The branch exists and you're on it; the commits are made. The "switch to a branch" step reduces to checking that the branch isn't `main` and is branched off a current `origin/main`.
- Take the feature description from `.sclaude/local/feature/plan.md` — that's what we agreed on while planning — and cross-check it against the `Requirement:` footers of the commits. Where the plan and the footers disagree, ask me: a mismatch means something changed during development, and either side may be right.
- **The "Requested by the customer (for QA)" section is the acceptance criteria, as a plain list.** The skill builds that section from the commits' footers; the agreed list replaces that draft, because it was written before the code and doesn't move with it. Copy it verbatim — identifiers and wording — in the skill's own order rule: what a tester would do first. **No checkboxes:** QA ticks the criteria in the issue, not in the pull request, and a second checklist here is a second place for a tick to land and disagree with the first.

<if:issue>  Open the section with one line: `QA checks these in #<issue> — tick them there.`

</if:issue>  The list is below if the orchestrator could read it out of the issue. If there's no block there, take it from the `## Acceptance criteria` heading of `.sclaude/local/feature/plan.md`, where step 1 put the same list; if neither has it, this feature was planned before criteria existed — build the section from the footers as the skill says, and say so when you report.

  Then use the footers the way the skill says, but as a check rather than a source. Walk `git log origin/main..HEAD --format='%(trailers:key=Requirement,valueonly)'` and compare:

  - a footer whose text has drifted from the criterion it names — the criterion's wording wins, and say so when you report;
  - a footer with no identifier — something asked for during development that isn't in the list. Add it to the section as an unnumbered item and tell me: it's either a criterion we missed or scope that grew, and I decide which.
  - a criterion with no footer anywhere — either it wasn't built or a commit was missing its footer. **Ask me before opening the pull request**; don't tick it, and don't quietly drop it from the list.

  Don't tick anything, here or in the issue, whatever the footers say. A tick is QA's word that the deployment does it, and a commit is not that check.
- **Open the pull request as a draft**: add `--draft` to the skill's `gh pr create`. It stays a draft until QA has accepted every issue it closes; then the orchestrator marks it ready, which is what lets anybody merge it. Don't assign anyone either — the orchestrator assigns the PR to its author and clears that at the same moment.
- The manuals (<manuals>) are updated here, as the skill requires. `.sclaude/local/feature/plan.md` is the source of what was promised.
- **Once the manuals are written, ask whether this feature earns a regression test — and expect the answer to be no.**

  The suite is a gate on every future feature, not a record of this one. Each spec is minutes on every stage of every cycle from now on, so the question is not "could this be tested" — everything could — but "if this broke silently six months from now, would we find out any other way, and how much would it cost us before we did".

  Look at what is already there before answering: the specs are few and each one opens with a paragraph saying what layer it covers that nothing else can. Match that bar or leave it alone.

  **Argue for a test only when all of these hold:**

  - **Breaking it is silent.** A crash, a type error or a failing build is already caught, and cheaper. What earns a spec is behaviour that goes wrong while everything still looks fine — a field that leaks rather than 500s, a permission that widens, a state that quietly stops being reached.
  - **The cost of not knowing is real.** Data somebody else can see, money, something irreversible. Not "a button moved".
  - **No cheaper layer covers it.** Every other part of the regression catches a class of break — the type checker, the linter, the project's own checks, the database's policies — and a spec is for what survives all of them. Name the layer you expected to catch it and say why it does not reach this.
  - **It will keep being true.** A test pinned to this month's copy or layout is a test somebody deletes in anger later.

  **Argue against — and this is the ordinary outcome — when** the change is cosmetic or a wording change; when it is one screen's own behaviour with no rule behind it; when a compile error or a red check would catch the same break; when the assertion would be about markup rather than about a rule; or when a spec would mostly re-run what an existing one already walks through.

  Tell me your answer either way, in one short paragraph: what would break, how we would find out without a test, and what it would cost in between. If the answer is a test, say **which existing spec it belongs in** before proposing a new file — a new case inside a spec that already signs in as the right people costs seconds, a new spec costs a fixture and a sign-in of its own. Do not write it in this session: you are opening a pull request, and a suite that grew without my agreeing to it is exactly the growth the question exists to prevent.
<if:issue>- This feature closes issue **#<issue>**. The PR body must end with `Closes #<issue>` on its own line, so GitHub links the issue and closes it on merge.
- Don't set a milestone: the orchestrator sets it, taking the one the pull request's issues belong to, and asks me when they disagree. That's its job because a milestone is the exact name of an existing repository milestone — it can check that, rather than guess.
</if:issue>

<block:acceptance>

<block:reopened>

About the `.sclaude/local/feature/` directory: it's a working directory, it's in `.gitignore`, and it must not be committed. The orchestrator checked the branch history for you — if it had gotten in, it would be stated below. Do **not** delete the directory: `.sclaude/local/feature/state.json` is the orchestrator's state, needed by the next step and removed together with the worktree by `sclaude done`. Leave the plan inside it too: the next step checks review comments against it.

<block:feature-in-history>

<include:dev-server>

<include:questions>

<include:friction>

**How this session ends.** You are step 3 of four; the `sclaude` orchestrator drives the steps from outside. Handling review comments is step 4 — a separate session with a different model, launched by the orchestrator once I say this step is done.

The orchestrator runs this step with restrictions: merge, deploy and anything leading to production simply won't run here. A rejection is the step's boundary, not a failure; `git push` of the branch and `gh pr create` are allowed — that's your job.

<include:report>

**When the pull request is open and the branch pushed, `sclaude` closes this session itself.** Write the marker first — `echo done > .sclaude/local/feature/session-done` — and then the report, with no tool call after it. About thirty seconds after your turn ends the session is closed and the report printed in the orchestrator's terminal; if I type anything in those thirty seconds, the closing is called off and the marker removed. sclaude then checks that the branch has a pull request and that its head is what is here; if not, it brings you back to this conversation to finish, at most twice. Leave the marker out when something needs my answer — then I close the session myself.

Once the pull request is open, tell me in that one message — in your own words, but cover all of it:

- the work in this session is done — the pull request is open, with its URL, and what's left open around it;
- **your verdict on a regression test**, in a sentence: no and why, or yes and which spec it belongs in. It goes here because it is a decision I have to make and nothing else in the cycle will ask me for it again;
- with the marker written, that `sclaude` closes this session itself; without it, that I should now close Claude with `/exit`;
- after that the `sclaude` orchestrator continues — it launches step 4 itself, I do nothing for that.

Then stop. Don't take on review comments and don't offer to: I can't say yes anyway, since the next step starts when this session closes.
