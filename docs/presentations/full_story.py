#!/usr/bin/env python3
"""Assemble one deck, the full story, from the three decks in src/.

Problem first, then how sclaude solves it, then the tools around it. Slides
are picked from the decks by their heading (an animated slide by its
aria-label) and lightly edited so that they read as one deck: the eyebrows
name this deck's parts, and a line that pointed at another deck points at a
part of this one. The cover, the part dividers, the closing slide and the
phone's three layers are written here.

build.py writes it beside the other decks as sclaude_full_story.html; run
alone, this writes it where it is told:

    python3 docs/presentations/full_story.py OUT.html
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
sys.path.insert(0, str(HERE))
from build import inline_images  # noqa: E402

SECTION = re.compile(r'<section class="slide[^"]*"[^>]*>.*?</section>', re.S)


def slides(name):
    out = {}
    for m in SECTION.finditer((SRC / name).read_text()):
        s = m.group(0)
        h = re.search(r'<h[12][^>]*>(.*?)</h[12]>', s, re.S)
        label = re.search(r'aria-label="([^"]*)"', s)
        if h or label:  # a slide with neither is never picked by name
            key = h.group(1) if h else label.group(1)
            # by the heading's words: markup inside it is not part of the name
            out[re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", key)).strip()] = s
    return out


def outside_slides(name):
    """What a deck carries besides its slides: the styles and scripts its
    slides need (the animated ones)."""
    return SECTION.sub("", (SRC / name).read_text()).strip()


def animations():
    """The animated slides draw their own eyebrow; it names this deck's
    parts, as the eyebrows of the slides picked below do."""
    s = outside_slides("vibe_coding_story.html")
    for old, new in [("'Chapter 1 · What I found first'", "'The problem · what I found first'"),
                     ("'Chapter 1 · Two months later'", "'The way out · two months later'")]:
        assert old in s, old
        s = s.replace(old, new)
    return s


D = slides("sclaude_in_details.html")
I = slides("sclaude_instruments.html")
V = slides("vibe_coding_story.html")


def pick(src, title, *edits):
    s = src[title]
    for old, new in edits:
        assert old in s, (title, old)
        s = s.replace(old, new)
    return s


def eyebrow(old, new):
    return (f'<div class="eyebrow">{old}</div>', f'<div class="eyebrow">{new}</div>')


COVER = '''<section class="slide cover">
  <div class="eyebrow">sclaude · the full story · 2026</div>
  <div class="grow" style="display:flex;flex-direction:column;justify-content:center;gap:28px">
    <h1><s class="muted" style="text-decoration-thickness:5px">Manageable</s> Scalable<br>AI coding</h1>
    <p class="lede" style="max-width:56ch">A ready toolkit for startups, PoCs and MVPs. An orchestrator keeps AI development controlled and cheap; a stack chosen for speed and a phone channel keep the work moving.</p>
    <div class="g3" style="max-width:1000px">
      <p class="muted small"><b style="color:var(--signal)">1 · The problem</b><br>why AI coding drifts, and what every team rebuilds</p>
      <p class="muted small"><b style="color:var(--signal)">2 · The orchestrator</b><br>how sclaude keeps the process in code</p>
      <p class="muted small"><b style="color:var(--signal)">3 · The tools around it</b><br>the stack, the laptop and the phone</p>
    </div>
  </div>
  <div class="row" style="justify-content:space-between;align-items:flex-end">
    <div class="chips"><span class="chip signal">Doable</span><span class="chip auto">Controllable</span><span class="chip cloud">Affordable</span></div>
    <p class="mono xs muted">Ilia Poliakov</p>
  </div>
</section>'''


def divider(n, title, lede):
    return f'''<section class="slide cover">
  <div class="eyebrow">Part {n} of 3</div>
  <div class="grow" style="display:flex;flex-direction:column;justify-content:center;gap:28px">
    <h1 style="font-size:72px">{title}</h1>
    <p class="lede" style="max-width:56ch">{lede}</p>
  </div>
</section>'''


PHONE = '''<section class="slide">
  <div class="head">
    <div class="eyebrow">The channel · three layers</div>
    <h2>Most phone moments are look, tap, done</h2>
    <p class="lede">A desk session shows up in the Claude mobile app. Everything else on the laptop needs a way in, and the right one depends on the moment.</p>
  </div>
  <div class="g3 grow">
    <div class="card auto">
      <div class="row" style="justify-content:space-between"><div class="k">Layer 1 · Claude app</div><span class="mono">~15%</span></div>
      <div class="bar"><span style="width:15%;background:var(--auto)"></span></div>
      <h3>Talk to the agent</h3>
      <ul class="ticks xs">
        <li>Continue the session the laptop started</li>
        <li>Read the plan, correct the scope, approve it</li>
        <li>Answer questions and permission prompts</li>
        <li>Give the next instruction on the way to a meeting</li>
      </ul>
      <p class="xs muted">Cannot reach the command line, the orchestrator, the feature on its test server or the logs.</p>
    </div>
    <div class="card cloud">
      <div class="row" style="justify-content:space-between"><div class="k">Layer 2 · the full kit</div><span class="mono">~5%</span></div>
      <div class="bar"><span style="width:5%;background:var(--cloud)"></span></div>
      <h3>Something stuck or unusual</h3>
      <ul class="ticks xs">
        <li><b>Tailscale:</b> one private network; SSH listens only there</li>
        <li><b>Termius:</b> SSH with a key made on the phone; sclaude, full-screen Claude, any command</li>
        <li><b>code-server:</b> VS Code in the phone's browser, on demand</li>
      </ul>
      <p class="xs muted">The spare key that always works, and too heavy for "restart the server": minutes of setup, three apps and a VPN.</p>
    </div>
    <div class="card signal">
      <div class="row" style="justify-content:space-between"><div class="k">Layer 3 · Telegram bot</div><span class="mono">~80%</span></div>
      <div class="bar"><span style="width:80%;background:var(--signal)"></span></div>
      <h3>Look at the result, press a button</h3>
      <ul class="ticks xs">
        <li>Open the web preview of the feature</li>
        <li>Restart something</li>
        <li>Answer "is the step done?"</li>
        <li>Extend the laptop's awake time</li>
      </ul>
      <p class="xs muted">Seconds of intent. Next slide.</p>
    </div>
  </div>
  <div class="split" style="align-items:end">
    <p class="punch" style="font-size:26px">The 80% deserves a client of its own. <em>Almost every developer had already built one.</em></p>
    <p class="small muted">Each in their own way, paid for in time and tokens, as Part 1 showed. So we built it once, for everyone. <span class="xs mono">Shares are a working estimate from daily use, not a benchmark.</span></p>
  </div>
</section>'''

CLOSE = '''<section class="slide cover">
  <div class="eyebrow">In summary</div>
  <div class="grow" style="display:flex;flex-direction:column;justify-content:center;gap:34px">
    <h1 style="font-size:60px">Find the flow everyone repeats.<br>Automate it once.<br>Keep people on the decisions.</h1>
    <div class="g3">
      <div class="col"><h2 style="color:var(--signal)">Doable</h2><p class="muted">Runs on the laptops a team already has, on free tiers, installed with one script.</p></div>
      <div class="col"><h2 style="color:var(--signal)">Controllable</h2><p class="muted">A fixed path, gates on evidence, rules that hold, people at every decision.</p></div>
      <div class="col"><h2 style="color:var(--signal)">Affordable</h2><p class="muted">Tokens spent on thinking only. Everything repeatable is a script.</p></div>
    </div>
    <p class="lede" style="max-width:70ch">The orchestrator owns the process; AI does what the process asks. Building it is closer to project management than to programming: design the flow, set the constraints, track the deviations, resolve the conflicts between rules.</p>
  </div>
  <div class="row" style="justify-content:flex-end;align-items:flex-end">
    <p class="mono xs muted">github.com/personalautomation/SClaude · MIT</p>
  </div>
</section>'''

deck = [
    COVER,
    # part 1 · the problem: where it started, the bicycles, the way out
    pick(D, "What we tried first, with plenty of budget",
         eyebrow("Why · where this started", "The problem · where this started")),
    pick(V, "Some were ahead of the whole planet. Others barely kept up.",
         eyebrow("Chapter 1 · Where it started", "The problem · then a startup")),
    pick(V, "The company became fragmented",
         eyebrow("Chapter 1 · The saddest part", "The problem · the saddest part")),
    pick(V, "Half their time went not into the product, but into tools",
         eyebrow("Chapter 1 · What I found first", "The problem · what I found first")),
    pick(V, "Everyone built their own tools — and fell into the same holes"),
    pick(I, "Every developer had built the same bicycle",
         eyebrow("What I found in the team", "The problem · the bicycles")),
    pick(I, "AI review is where the know-how moved",
         eyebrow("The other bicycle everyone builds", "The problem · the bicycle that costs the most"),
         ("The sclaude deck shows how.", "Part 2 shows how.")),
    pick(V, "All local tools go into the company's git. As is.",
         eyebrow("Chapter 1 · The first decision", "The way out · the first decision")),
    pick(V, "Did developers start spending more time on the product? No.",
         eyebrow("Chapter 1 · Two months later", "The way out · two months later")),
    pick(V, "One shared tool in the company's git — everyone contributes, it grows"),
    pick(D, "Do not make the model the process engine",
         eyebrow("Why · the durable lesson", "The way out · the durable lesson")),
    # part 2 · the orchestrator
    divider(2, "The orchestrator owns the process",
            "sclaude runs a feature from issue to production on a fixed path. The model is called only where judgement is needed; everything else is code, rules and evidence."),
    pick(D, "The model handles judgement. The orchestrator handles the rest.",
         eyebrow("Why · division of labour", "The orchestrator · division of labour")),
    pick(D, "One feature, one fixed path"),
    pick(D, "Contain. Curate. Control."),
    pick(I, "Three features at once, and none of them can break another",
         eyebrow("The second pain · parallel features", "How a feature flows · contain")),
    pick(D, "Each step gets its own model, permissions and exit"),
    pick(D, "Six habits that cut the token bill"),
    pick(D, "Built for the bad days too"),
    pick(D, "How sclaude avoids the four ways review goes wrong"),
    pick(D, "AI reviews. The person gets the decision surface."),
    pick(D, "Start with the tools locked down, on purpose"),
    pick(D, "Three feedback loops, three horizons"),
    pick(D, "The retrospective is how the team learns"),
    pick(D, "Where a lesson ends up, and who decides"),
    pick(D, "Process, prompts and lessons become company capital",
         eyebrow("Why · knowledge as capital", "What it adds up to · knowledge as capital")),
    pick(V, "Metrics, without a single extra action from the developer",
         eyebrow("Chapter 1 · Metrics", "What it adds up to · metrics")),
    pick(V, "Raw metrics bore people. Watching their own feature get built doesn't.",
         eyebrow("Chapter 1 · Gamification", "What it adds up to · gamification")),
    pick(V, "However much we talk about AI, it is built on your data",
         eyebrow("Chapter 1 · Data", "What it adds up to · data")),
    pick(V, "I went another way, and I am proud of it",
         eyebrow("Chapter 1 · How others do it", "What it adds up to · how others do it")),
    pick(D, "One copy for everybody. One record per feature."),
    pick(D, "A simple idea, made explicit exception by exception"),
    # part 3 · the tools around it
    divider(3, "The tools around it",
            "A stack chosen for speed and for the model, a laptop that serves as the build machine, and a phone that is only a channel to the orchestrator."),
    pick(I, "Five criteria, four places, one flow"),
    pick(V, "Why is sclaude built for exactly this infrastructure?",
         eyebrow("Chapter 2 · A question from my DMs", "Why each tool · a question from my DMs")),
    pick(I, "Four managed services instead of an ops team"),
    pick(V, "Next.js turned out to be a lucky framework for vibe-coding",
         eyebrow("Chapter 2 · Special thanks", "Why each tool · special thanks")),
    pick(I, "Step away from the desk. The work keeps going."),
    pick(I, "In a startup, the laptop is the server"),
    pick(I, "The agent, the machine and the way in",
         ("Its own deck follows.", "Part 2 of this deck.")),
    PHONE,
    pick(I, "The Telegram client: a channel to the orchestrator",
         ("and the laptop carries on by itself.</p>",
          "and the laptop carries on by itself. A \"Publish?\" arrives with the commands it would run.</p>")),
    pick(I, "The classic path and the sclaude path"),
    pick(I, "keepawake: awake while there is work, asleep when there is none"),
    CLOSE,
    pick(V, "I can help with your own process — not only with sclaude"),
    pick(I, "What the claims stand on", ("in these decks", "in this deck")),
]


NAME = "sclaude_full_story.html"


def write(out):
    head = (SRC / "head.html").read_text().replace("{{TITLE}}", "sclaude: The Full Story")
    tail = ((SRC / "tail.html").read_text()
            .replace("{{MARK}}", "sclaude · the full story").replace("{{OTHER}}", ""))
    page = (head + "\n\n".join(deck) + "\n"
            + animations() + "\n" + tail)
    assert "{{" not in page.replace("{{IMG:", "")
    Path(out).write_text(inline_images(page))
    return len(deck)


if __name__ == "__main__":
    print(sys.argv[1], write(sys.argv[1]), "slides")
