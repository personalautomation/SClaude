A session of step "<step>" of the feature "<feature>" has ended, and something got in its way. Work out what exactly, and fix the tooling before the next session starts — the same step's next session, or the next step's first.

<body>

**How this ends.** Present me a plan: what to lift, why that's safe, and exactly what changes in which file. Split it by step — step 1 has its own permissions, steps 2–4 theirs. Once I approve, make the change yourself and commit it in the worktree, on the feature's branch, as **Committing** above says.

If there's nothing to fix — every entry is a deliberate ban — say so and change nothing. An empty change is worse than no change.

**Then, as the very last line you print, one line for the orchestrator:**

```
sclaude-verdict: lifted|deliberate|deferred|mixed — <one short clause>
```

Pick `lifted` if you loosened or removed a restriction (an `allow` in the policy, or a fix to the project), `deliberate` if you changed nothing because every entry was a ban working as intended, `deferred` if you only put entries off into the deferred file, `mixed` if more than one of these happened. The clause after the dash is for a human reading the issue later — "subagents restored to step 1", "all four entries were the merge ban". Keep it to one line: everything after the first newline is discarded.

This line is read out of your transcript once you exit, and it is the only part of your answer a machine looks at. It does not replace the summary below — write both.

**Once the change is committed — or, after the plan, once you have decided there is nothing to change — `sclaude` closes this session itself.** Write the marker first — `echo done > <done-marker>` — and then the report, with no tool call after it. About thirty seconds after your turn ends the session is closed and the report printed in the orchestrator's terminal; if I type anything in those thirty seconds, the closing is called off and the marker removed. Before I have approved a plan you cannot write the marker (plan mode); if you end there, with nothing to fix, I close the session myself.

Either way — a commit made or nothing to fix — tell me then, in one message that ends with the verdict line and is the last thing you write: once the session has closed, the `sclaude` orchestrator prints its last message, and an earlier one is lost there. In your own words, but cover all of it:

- where you departed from the plan I approved, and why — "none" if none;

- the work in this session is done — what you changed and why, or that there was nothing to fix, and what's left open;
- with the marker written, that `sclaude` closes this session itself; without it, that I should now close Claude with `/exit`;
- after that the `sclaude` orchestrator continues — it pushes the feature's branch and carries on with the session this fix was made for, I do nothing for that.

Then stop.
