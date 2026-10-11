**The orchestrator already started a dev server** for this worktree: open it at `<dev-url>`; log at `.feature/dev.log`. Other features being worked on at the same time have servers of their own at other addresses — `localhost:3000` without a feature name is a list of them, not this feature. Don't start a server yourself: `next dev` launched from a session stays in its process group and blocks you from exiting, and exiting is how this step ends. If you do need to start or restart it, detach it and keep its port:

```
PORT=<dev-port> SCLAUDE_DEV_URL=<dev-url> setsid nohup npm run dev > .feature/dev.log 2>&1 < /dev/null &
```

<if:db-api>**This feature has a local Supabase of its own** (API at `<db-api>`), and the dev server, the regression and this session all point at it — `SUPABASE_WORKDIR` in your environment sends a plain `npx supabase …` there too. Other features have their own; the main repository's stack is not yours. So `npx supabase migration up` applies your migrations to this feature alone, and `npx supabase db reset` rebuilds this feature's database from its migrations without touching anyone else's — run the project's seed afterwards if you need people to sign in as. Don't pass `--workdir`: it would point the CLI somewhere else.

</if:db-api><if:shared-db>**This feature works against `<shared-db>`, a database the whole team shares.** Reading is fine; changing the schema is not — a migration applied there lands under every other feature pointed at it. If the work turns out to need a migration, write it but don't push it to `<shared-db>`: tell the human, who can move the feature to its own local database. The hook will ask before any `supabase db push`.

</if:shared-db>**Chrome is already running** with a debug port, started by the orchestrator too; log at `.feature/chrome.log`. The chrome-devtools MCP server attaches to it, so its tools work straight away. If it ever isn't there, `chrome-debug` starts it and detaches on its own. The browser is shared: `list_pages` may show tabs of other features, which other sessions are working in. Work only in tabs on `<dev-url>` — open one with `new_page` if there isn't one — and leave the others alone.

For a phone-width check use `emulate`, not `resize_page`. `resize_page` resizes the real window and floors at the window's own minimum width, about 500px: ask for 390 and you get 500, silently — no error, nothing in the result to say the number changed. `emulate` sets the viewport through the protocol and honours it: `viewport: "390x844x3,mobile,touch"`. Read the viewport back before trusting any narrow-width conclusion — a verdict drawn from an unchecked 500px is a verdict about a tablet.

A touch swipe has no tool: chrome-devtools `drag` is a mouse drag, and `Input.synthesizeScrollGesture` scrolls nothing here — on a tab that is not in front it never returns at all. Drive raw touch events through the debug port instead, from a short Node script inside the worktree (under `.feature/`, so `@playwright/test` resolves; delete it afterwards). Connect with `chromium.connectOverCDP("http://localhost:9222")`. This feature may have more than one tab on `<dev-url>`, so mark yours first — `evaluate_script` `window.name = "swipe-target"` — and pick it by that name, then `bringToFront()`. Open `context.newCDPSession(page)`, set the phone viewport on it with `Emulation.setDeviceMetricsOverride` and `Emulation.setTouchEmulationEnabled`, then send `Input.dispatchTouchEvent`: `touchStart`, several `touchMove`s, `touchEnd`. A reload drops that emulation — set it again and read `innerWidth` back. Run the script under `timeout 60`, and end it with `process.exit(0)`, not `browser.close()`: the browser is shared. In a spec the same `dispatchTouchEvent` sequence through `page.context().newCDPSession(page)` is the swipe Playwright lacks.

There is no way to load a page with JavaScript disabled: the MCP server has no tool for it, and the protocol's own switch lives on a debugger connection that dies with the command that set it. To check that something still works without JavaScript, read the server-rendered markup instead and look at it: whether the form is a plain `method="POST"`, whether the link is a plain `<a href>`.

On a public page `curl -s <url>` is enough. On a page behind sign-in it is not: `curl` carries no session cookie, and `proxy.ts` answers it with a 307 to `/?dialog=login&next=…` — correct behaviour that answers nothing about your markup. The auth cookies are `HttpOnly`, so `document.cookie` will not hand them over either. Fetch through the already-signed-in browser instead, with chrome-devtools `evaluate_script`:

```
await fetch('<path>', { credentials: 'same-origin' }).then(r => r.text())
```

Same session, same server-rendered HTML, no cookie jar to build.
