A fixing session for the feature "<feature>" has ended — the one the orchestrator opened after the "<step>" regression came back red. Something got in *its* way. Work out what exactly, and fix the tooling.

This is not a step of the cycle. A fixing session runs with the settings of the step it repairs, inside the feature's worktree, and it is opened by `regression_fix` (`sclaude/lib/regression.sh`) rather than by `run_step`. What it was doing when it hit the obstacle was reading a regression log and repairing whatever the run had found — so the friction here is usually about that: a check it could not run, a file it could not reach, a command the bans refused while it was trying to reproduce a failure.

<body>

**One thing to weigh that a step's review does not.** A fixing session is opened at most twice per stage, and only when a run is already red — so an obstacle here costs more than the same obstacle in a step: the feature is stuck, the clock is running, and the human is usually not watching. Judge accordingly. But the opposite also holds: a ban that fired here may be right precisely because a fixing session is the wrong place to do that thing — deploying, merging and promoting are my steps whether the regression is red or green.

**How this ends.** Present me a plan: what to lift, why that's safe, and exactly what changes in which file. Once I approve, make the change yourself and commit it to the branch you are on by this repo's rules: a Conventional Commits subject, a body, and an unbroken footer block at the end.

If there's nothing to fix — every entry is a deliberate ban — say so and change nothing. An empty change is worse than no change.

**Then, as the very last line you print, one line for the orchestrator:**

```
sclaude-verdict: lifted|deliberate|deferred|mixed — <one short clause>
```

Pick `lifted` if you loosened or removed a restriction, `deliberate` if you changed nothing because every entry was a ban working as intended, `deferred` if you only put entries off into the deferred file, `mixed` if more than one of these happened. The clause after the dash is for a human reading the issue later — "curl allowed for reproducing the failure", "both entries were the deploy ban". Keep it to one line: everything after the first newline is discarded.

This line is read out of your transcript once you exit, and it is the only part of your answer a machine looks at. It does not replace the summary below — write both.

**Once the change is committed — or, after the plan, once you have decided there is nothing to change — `sclaude` closes this session itself.** Write the marker first — `echo done > <done-marker>` — and then the report, with no tool call after it. About thirty seconds after your turn ends the session is closed and the report printed in the orchestrator's terminal; if I type anything in those thirty seconds, the closing is called off and the marker removed. Before I have approved a plan you cannot write the marker (plan mode); if you end there, with nothing to fix, I close the session myself.

Either way — a commit made or nothing to fix — tell me then, in one message that ends with the verdict line and is the last thing you write: once the session has closed, the `sclaude` orchestrator prints its last message, and an earlier one is lost there. In your own words, but cover all of it:

- where you departed from the plan I approved, and why — "none" if none;

- the work in this session is done — what you changed and why, or that there was nothing to fix, and what's left open;
- with the marker written, that `sclaude` closes this session itself; without it, that I should now close Claude with `/exit`;
- after that the `sclaude` orchestrator continues — it pushes the commit and carries the feature on from where the regression left it, I do nothing for that.

Then stop.
