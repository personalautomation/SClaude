# Getting started

## Install

```bash
git clone git@github.com:personalautomation/SClaude.git ~/sclaude
cd ~/sclaude && ./install.sh
sclaude doctor          # what this machine still lacks, and how to fix it
```

The installer asks how this machine takes updates from the public `main` and
whether it sends fixes back; by default nothing is sent without your yes.
`sclaude doctor` lists every gap with the command that fixes it.

## Your first feature

```bash
cd <your product> && sclaude new
```

The first `sclaude new` in a product offers to write its config, read from what
is already there — tests from `package.json`, manuals and migrations from the
layout, the board from the repository's GitHub project — and shows it for
confirmation before anything is written.

Then pick an issue. SClaude creates the feature's sandbox and starts
[step 1](The-Cycle): Claude tells you what it understood and waits for you to
correct it before it plans.

## The commands you will use most

```bash
sclaude                 # the menu: features in progress
sclaude new [name]      # start a feature at step 1
sclaude <name>          # continue a feature from its current step
sclaude status          # every feature and its step
sclaude actions [name]  # everything you can do with one feature
sclaude config          # the product's settings, each one explained
sclaude done <name>     # clean up after the merge
```

## The skills

| skill | what it does |
|---|---|
| `/pr` | opens a pull request the GitHub-flow way |
| `/sreview` | review-and-fix rounds until the review finds nothing substantive; your answers become policies |
| `/sdemo` | records a demo of the feature, a video per scenario, with a link to take over any step by hand and a link to any moment, with a point on the frame, to send Claude with a remark |
| `/isleep` | night mode: Claude decides instead of asking and leaves a morning summary |

## The guides

| read | for |
|---|---|
| [Setting up](https://github.com/personalautomation/SClaude/blob/main/docs/setup.md) | the environment, what is required, installation |
| [Using sclaude](https://github.com/personalautomation/SClaude/blob/main/docs/sclaude-guide.md) | every command, a feature from start to finish |
| [How the cycle is kept in line](https://github.com/personalautomation/SClaude/blob/main/docs/cycle.md) | gates, refusals, rollback, metrics |
| [For a team](https://github.com/personalautomation/SClaude/blob/main/docs/team.md) | one copy, the product's config, layered rules |
| [Privacy](https://github.com/personalautomation/SClaude/blob/main/docs/privacy.md) | what leaves your machine |
| [The tools](https://github.com/personalautomation/SClaude/blob/main/docs/tools.md) | the skills, the proxy, chrome-debug, keepawake and the bot |
