#!/usr/bin/env python3
#
# The bot's strings in two languages.
#
# Telegram reports the client's language in from.language_code on every message
# and press. Russian is for those whose client is Russian; everyone else,
# clients with no language at all included, gets English. There is nothing to
# guess from a country code or the time of day here: Telegram says so directly,
# and that is the only reliable source.
#
# The language is remembered in the state rather than in memory alone: the
# daemon sends the warning about imminent sleep by itself, without an incoming
# update, and at that moment there is nobody to ask — the last known value stays
# the only thing it has.
#
#   t("menu.title")                 the string in the current language
#   t("holders.ssh", n=2)           with substitution
#   set_lang("en") / current()      switching and querying

DEFAULT = "en"

# Key → (Russian, English). The order within a pair is the same everywhere, so
# that a divergence is visible to the eye when reading.
STRINGS = {
    # menu
    "menu.title":        ("<b>%(host)s</b>\nЧто делаем?",
                          "<b>%(host)s</b>\nWhat shall we do?"),
    "menu.extend":       ("💤 Keepawake", "💤 Keepawake"),
    "menu.status":       ("📊 Статус", "📊 Status"),
    "menu.chrome":       ("🌐 Chrome", "🌐 Chrome"),
    "menu.sclaude":      ("📋 Sclaude", "📋 Sclaude"),
    "menu.code":         ("💻 Code-server", "💻 Code-server"),
    "menu.settings":     ("⚙️ Настройки", "⚙️ Settings"),
    "menu.back":         ("‹ Назад", "‹ Back"),
    "menu.button":       ("☰ Меню", "☰ Menu"),
    "anchor.hint":       ("Кнопка <b>☰ Меню</b> под полем ввода открывает "
                          "меню в любой момент.",
                          "The <b>☰ Menu</b> button below the input box opens "
                          "the menu at any time."),
    # Command descriptions — the same text as the hints in the list when
    # typing "/". Written from the use, not the mechanics: a person reads them
    # to choose, not to find out what is inside.
    # The bot's profile: the description before the first message ("What
    # can this bot do?", 512 characters at most) and the short one on its
    # page (120). Set at start when they or the bot changed (Bot.describe),
    # so they follow the bot; an edit in @BotFather stays until then.
    "bot.description":   ("Работа с ноутбуком с телефона.\n\n"
                          "• sclaude: у каждой фичи свой топик — её вопросы, "
                          "карточка с шагом, ▶️ продолжить, ⚙️ действия, "
                          "dev-сервер и code-server на её worktree.\n"
                          "• keepawake: ноутбук не спит, пока идёт работа; "
                          "за полчаса до сна бот спросит.\n"
                          "• В главном меню — статус, Chrome, code-server, "
                          "список фич и новая фича.",
                          "Your laptop, from the phone.\n\n"
                          "• sclaude: every feature has its own topic — its "
                          "questions, a card with its step, ▶️ continue, "
                          "⚙️ actions, its dev server and code-server on its "
                          "worktree.\n"
                          "• keepawake: the laptop stays awake while work goes "
                          "on; half an hour before sleep the bot asks.\n"
                          "• The main menu has status, Chrome, code-server, "
                          "the feature list and a new feature."),
    "bot.short":         ("Фичи sclaude по топикам, сон ноутбука и dev-серверы — "
                          "с телефона.",
                          "sclaude features by topic, the laptop's sleep and dev "
                          "servers — from the phone."),
    "cmd.menu":          ("Главное меню", "Main menu"),
    "cmd.awake":         ("Не спать: на час, до времени, совсем",
                          "Stay awake: an hour, until a time, forever"),
    "cmd.extend":        ("Продлить на час", "Extend by an hour"),
    "cmd.sleep":         ("Снять блокировки и уснуть", "Release and sleep"),
    "cmd.chrome":        ("Chrome с отладкой и dev-сервер",
                          "Chrome with debugging and the dev server"),
    "cmd.code":          ("Code-server: запуск и перезапуск",
                          "Code-server: start and restart"),
    "cmd.sclaude":       ("Фичи в работе по репозиториям",
                          "Features in progress, by repository"),
    "cmd.settings":      ("Язык, инструкции, перезапуск бота",
                          "Language, docs, restart the bot"),
    "cmd.status":        ("Кто держит и сколько осталось",
                          "Who is holding and how long is left"),

    # the "stay awake" submenu
    "awake.title":       ("<b>keepawake</b>\nСейчас держим до <b>%(until)s</b>.\n"
                          "Что делаем?",
                          "<b>keepawake</b>\nCurrently held until "
                          "<b>%(until)s</b>.\nWhat shall we do?"),
    "awake.title.free":  ("<b>keepawake</b>\nУдержания сейчас нет.\n"
                          "Что делаем?",
                          "<b>keepawake</b>\nNothing is holding right now.\n"
                          "What shall we do?"),
    "awake.manual":      ("\n<i>Продлено вручную. Когда срок выйдет, вернётся "
                          "обычный расчёт: держатели дают час с последней "
                          "активности.</i>",
                          "\n<i>Extended manually. When it runs out the usual "
                          "rules come back: holders give an hour from the last "
                          "activity.</i>"),
    "awake.h1":          ("☕ На час", "☕ One hour"),
    "awake.h2":          ("☕ На четыре", "☕ Four hours"),
    "awake.h3":          ("☕ На сутки", "☕ One day"),
    "awake.until":       ("🕒 До времени…", "🕒 Until a time…"),
    "awake.forever":     ("♾ Не засыпать совсем", "♾ Never sleep"),
    "awake.release":     ("🛑 Снять блокировки и уснуть", "🛑 Release and sleep"),
    "span.hours":        ("%(h)dч %(m)02dмин", "%(h)dh %(m)02dm"),
    "span.minutes":      ("%(m)d мин", "%(m)d min"),
    "awake.ask":         ("До которого часа не спать?\n"
                          "Ответьте временем — <code>23:30</code> или "
                          "<code>7:00</code>. Время сегодняшнее; если оно уже "
                          "прошло, поймём как завтрашнее.\n"
                          "<i>Отмена — /menu.</i>",
                          "Until what time should it stay awake?\n"
                          "Reply with a time — <code>23:30</code> or "
                          "<code>7:00</code>. Today\u2019s clock; if it has "
                          "already passed, we read it as tomorrow.\n"
                          "<i>Cancel with /menu.</i>"),
    # A short line for the second message — the one that raises the input box.
    # The long question already stands above, and repeating it whole means
    # writing the same thing to the person twice in a row.
    "awake.ask.now":     ("👇 Время сюда:", "👇 Time here:"),
    "awake.hint":        ("ЧЧ:ММ, например 23:30", "HH:MM, e.g. 23:30"),
    "awake.badtime":     ("Не понял время. Нужен формат <code>ЧЧ:ММ</code>, "
                          "например <code>23:30</code>. <i>Отмена — /menu.</i>",
                          "I did not understand that time. Use "
                          "<code>HH:MM</code>, e.g. <code>23:30</code>. "
                          "<i>Cancel with /menu.</i>"),
    "awake.forever.ok":  ("♾ Не засыпаем. Держим, пока не снимете это сами "
                          "кнопкой «Снять блокировки и уснуть».",
                          "♾ Staying awake. The hold lasts until you release "
                          "it yourself with \u201cRelease and sleep\u201d."),
    "awake.released":    ("🛑 Удержание снято. Дальше Windows усыпит ноутбук "
                          "по своему таймеру простоя.",
                          "🛑 Hold released. Windows will now put the laptop "
                          "to sleep on its own idle timer."),

    # chrome
    "chrome.title":      ("<b>chrome-debug</b>\n%(state)s\n%(proxy)s\n%(gate)s\n\n"
                          "<b>Фичи</b>\n%(features)s\n\n"
                          "<i>Ссылка — для телефона; адрес под ней — для "
                          "браузера на ноутбуке. Остановленная фича запускается "
                          "сама, когда её открывают, а неоткрытая полчаса — "
                          "останавливается. Окно Chrome на ноутбуке, отладочный "
                          "порт %(port)s.</i>",
                          "<b>chrome-debug</b>\n%(state)s\n%(proxy)s\n%(gate)s\n\n"
                          "<b>Features</b>\n%(features)s\n\n"
                          "<i>The link is for the phone; the address under it "
                          "is for the browser on the laptop. A stopped feature "
                          "starts when it is opened, and one nobody opens for "
                          "half an hour stops. The Chrome window is on the "
                          "laptop, debug port %(port)s.</i>"),
    "chrome.feature":    ("• %(link)s — %(state)s\n   <code>%(local)s</code>",
                          "• %(link)s — %(state)s\n   <code>%(local)s</code>"),
    "chrome.running":    ("✅ работает", "✅ running"),
    "chrome.stopped":    ("⏹ остановлена", "⏹ stopped"),
    "chrome.nofeatures": ("Ни у одной фичи ещё нет dev-сервера.",
                          "No feature has a dev server yet."),
    "chrome.proxyup":    ("✅ sclaude-proxy отвечает на :3000",
                          "✅ sclaude-proxy answering on :3000"),
    "chrome.proxydown":  ("⏹ sclaude-proxy не отвечает — фичи не открыть",
                          "⏹ sclaude-proxy is not answering — features cannot be opened"),
    "chrome.open":       ("🌐 Ноутбук", "🌐 Laptop"),
    "chrome.featstop":   ("⏹ Остановить", "⏹ Stop"),
    "chrome.phoneopen":  ("📲 Телефон", "📲 Phone"),
    "chrome.gateup":     ("📲 «Телефон» открывает фичу прямо в Telegram, "
                          "с адресной строкой. Пускает только вас.",
                          "📲 \u201cPhone\u201d opens the feature right in Telegram, "
                          "with an address bar. Only you are let in."),
    "chrome.gatedown":   ("🔒 Доступ с телефона выключен — включается в Настройках.",
                          "🔒 Phone access is off — it is turned on in Settings."),
    "chrome.gatefail":   ("⚠️ Доступ с телефона не включился:\n<pre>%(log)s</pre>\n"
                          "<i>Нужно один раз: funnel разрешён для ноутбука в политике "
                          "tailnet и <code>sudo tailscale set --operator=$USER</code>.</i>",
                          "⚠️ Phone access did not turn on:\n<pre>%(log)s</pre>\n"
                          "<i>Needed once: funnel allowed for the laptop in the tailnet "
                          "policy, and <code>sudo tailscale set --operator=$USER</code>.</i>"),
    "chrome.all":        ("Все фичи — localhost:3000", "All features — localhost:3000"),
    "chrome.stopbrowser": ("⏹ Chrome", "⏹ Chrome"),
    "chrome.up":         ("✅ браузер запущен", "✅ browser running"),
    "chrome.down":       ("⏹ браузер не запущен", "⏹ browser not running"),
    "chrome.output":     ("<b>chrome-debug</b>\n<pre>%(body)s</pre>",
                          "<b>chrome-debug</b>\n<pre>%(body)s</pre>"),
    "chrome.start":      ("▶️ Запустить", "▶️ Start"),
    "chrome.restart":    ("🔄 Перезапуск", "🔄 Restart"),
    "chrome.stop":       ("⏹ Остановить", "⏹ Stop"),

    # settings
    "svc.title":         ("<b>Настройки</b>", "<b>Settings</b>"),
    "svc.repos":         ("📁 Репозиторий", "📁 Repository"),
    "svc.docs":          ("📖 Инструкции", "📖 Instructions"),
    "svc.lang":          ("🌍 Язык", "🌍 Language"),
    "svc.phoneon":       ("📲 Доступ с телефона: включён", "📲 Phone access: on"),
    "svc.phoneoff":      ("🔒 Доступ с телефона: выключен", "🔒 Phone access: off"),
    "svc.phonewarm":     ("<b>Настройки</b>\n\n📲 Доступ с телефона включён. Tailscale "
                          "начинает пропускать его примерно через 1,5 минуты; дальше "
                          "«📲 Телефон» в карточке фичи (в её топике) открывает её в "
                          "Telegram, а в карточке chrome-debug — список всех фич.",
                          "<b>Settings</b>\n\n📲 Phone access is on. Tailscale starts "
                          "carrying it in about a minute and a half; then \u201c📲 Phone\u201d "
                          "on a feature's card (in its topic) opens it in Telegram, and "
                          "on the chrome-debug card the list of every feature."),

    # the language switch
    "lang.title":        ("<b>Язык</b>\nСейчас: <b>%(now)s</b>\n\n"
                          "<i>«Как в Telegram» — брать язык из клиента, как "
                          "было раньше. Выбранный вручную держится, пока не "
                          "смените здесь же.</i>",
                          "<b>Language</b>\nCurrently: <b>%(now)s</b>\n\n"
                          "<i>\u201cFollow Telegram\u201d takes the language "
                          "from your client, as before. A language picked here "
                          "stays until you change it here.</i>"),
    "lang.ru":           ("🇷🇺 Русский", "🇷🇺 Russian"),
    "lang.en":           ("🇬🇧 English", "🇬🇧 English"),
    "lang.auto":         ("🔄 Как в Telegram", "🔄 Follow Telegram"),
    "lang.name.ru":      ("русский", "Russian"),
    "lang.name.en":      ("английский", "English"),
    "lang.auto.now":     ("как в Telegram (%(what)s)",
                          "following Telegram (%(what)s)"),
    "lang.set":          ("🌍 Язык: <b>%(now)s</b>.",
                          "🌍 Language: <b>%(now)s</b>."),

    # The docs. Split into sections: Telegram has a ceiling of 4096 bytes per
    # message, and both the installation and the design need telling.
    "docs.menu":         ("<b>Инструкции</b>\nЧто показать?",
                          "<b>Instructions</b>\nWhat should I show?"),
    "docs.why":          ("🧩 Зачем что нужно", "🧩 What is what for"),
    "docs.usage":        ("📱 Как пользоваться", "📱 How to use it"),
    "docs.arch":         ("🏗 Как это устроено", "🏗 How it works"),
    "docs.install":      ("💾 Установка с нуля", "💾 Install from scratch"),
    "docs.holders":      ("🔒 Держатели", "🔒 Holders"),
    "docs.files":        ("📂 Файлы и службы", "📂 Files and services"),
    "docs.trouble":      ("🔧 Если что-то не так", "🔧 Troubleshooting"),
    "svc.restart":       ("🔁 Перезапуск демона", "🔁 Restart daemon"),
    "svc.restarting":    ("🔁 Перезапускаюсь…\nСообщу, когда поднимусь.",
                          "🔁 Restarting…\nI will report once I am back."),
    "svc.restarted":     ("✅ Демон перезапущен и снова на связи.",
                          "✅ Daemon restarted and back online."),

    # code-server
    "code.title":        ("<b>code-server</b>\n%(state)s\n%(folder)s\n\n"
                          "С телефона:\n%(url)s\n\n"
                          "С этого ноутбука:\n%(local)s\n\n"
                          "<i>Гаснет сам после часа простоя. "
                          "Пароль — в ~/.config/code-server/config.yaml</i>",
                          "<b>code-server</b>\n%(state)s\n%(folder)s\n\n"
                          "From your phone:\n%(url)s\n\n"
                          "From this laptop:\n%(local)s\n\n"
                          "<i>Shuts down after an hour idle. "
                          "Password is in ~/.config/code-server/config.yaml</i>"),
    "code.running":      ("✅ работает", "✅ running"),
    "code.stopped":      ("⏹ погашен — поднимется сам при переходе по ссылке "
                          "с ноутбука",
                          "⏹ down — opening the laptop link brings it back"),
    "code.start":        ("▶️ Запустить", "▶️ Start"),
    "code.folder":       ("Открыт: <b>%(name)s</b>", "Open in: <b>%(name)s</b>"),
    "code.reopen":       ("📂 Открыть %(name)s", "📂 Open %(name)s"),
    "code.restart":      ("🔄 Перезапуск", "🔄 Restart"),
    "code.stop":         ("⏹ Остановить", "⏹ Stop"),

    # repositories and features
    "repo.pick":         ("<b>Какой репозиторий смотреть</b>",
                          "<b>Which repository?</b>"),
    "repo.none":         ("<b>%(name)s</b> — фич в работе нет.\n\n"
                          "Ветка <b>%(branch)s</b>\n"
                          "Последний коммит: %(commit)s%(links)s\n"
                          "<i>%(when)s</i>\n%(extra)s",
                          "<b>%(name)s</b> — no features in progress.\n\n"
                          "Branch <b>%(branch)s</b>\n"
                          "Last commit: %(commit)s%(links)s\n"
                          "<i>%(when)s</i>\n%(extra)s"),
    # The captions of the links under a commit. Short: on a phone
    # "PR #89 · Issue #20" fits on one line, whereas two bare addresses would
    # take three.
    "repo.pr":           ("PR #%(n)s", "PR #%(n)s"),
    "repo.issue":        ("Задача #%(n)s", "Issue #%(n)s"),
    "repo.dirty":        ("⚠️ незакоммиченных изменений: %(n)d",
                          "⚠️ uncommitted changes: %(n)d"),
    "repo.ahead":        ("⬆️ не отправлено коммитов: %(n)d",
                          "⬆️ commits not pushed: %(n)d"),
    "repo.clean":        ("✅ чисто, всё отправлено", "✅ clean, everything pushed"),
    "repo.nocommits":    ("<b>%(name)s</b> — фич в работе нет.\n\n"
                          "<i>В репозитории ещё нет коммитов.</i>\n%(extra)s",
                          "<b>%(name)s</b> — no features in progress.\n\n"
                          "<i>The repository has no commits yet.</i>\n%(extra)s"),
    # No table under the header: a feature's name and its step are on the
    # buttons, and the path to the worktree is not needed on a phone — there is
    # nothing to open it with there anyway. The branch breakdown from the same
    # table goes as well: it is about branches without features, that is about
    # exactly what is not in this list.
    "repo.count":        ("<b>%(name)s</b> — фич в работе: %(n)d",
                          "<b>%(name)s</b> — features in progress: %(n)d"),
    # There are eight buttons, and there can be more features. While the
    # sclaude status table lay under the header, the extra ones were at least
    # visible; without it they disappeared from the chat entirely — and the
    # counter gave no clue where they were. We name them here.
    "repo.rest":         ("\nНе поместились: %(rest)s\nОткрыть их можно из терминала.",
                          "\nNot shown: %(rest)s\nOpen them from the terminal."),
    "repo.norepos":      ("Не нашёл ни одного git-репозитория в домашнем каталоге.",
                          "No git repositories found in the home directory."),
    "repo.refresh":      ("🔄 Обновить", "🔄 Refresh"),
    "repo.torepos":      ("‹ К репозиториям", "‹ Repositories"),
    "feat.card":         ("<b>%(repo)s</b> / <b>%(slug)s</b>%(links)s\n"
                          "Шаг: %(step)s\n"
                          "Worktree: <code>%(wt)s</code>%(session)s",
                          "<b>%(repo)s</b> / <b>%(slug)s</b>%(links)s\n"
                          "Step: %(step)s\n"
                          "Worktree: <code>%(wt)s</code>%(session)s"),
    # The feature's card in its topic: the dev server and code-server lines.
    "card.dev":          ("\n\n🖥 Dev-сервер: %(state)s\n%(link)s · <code>%(local)s</code>",
                          "\n\n🖥 Dev server: %(state)s\n%(link)s · <code>%(local)s</code>"),
    "card.phonelink":    ("с телефона", "from the phone"),
    "card.nodev":        ("\n\n🖥 Dev-сервера у фичи ещё нет.",
                          "\n\n🖥 The feature has no dev server yet."),
    "card.code":         ("\n💻 code-server: <a href=\"%(url)s\">открыть worktree</a> · "
                          "<code>%(local)s</code>",
                          "\n💻 code-server: <a href=\"%(url)s\">open the worktree</a> · "
                          "<code>%(local)s</code>"),
    "card.nocode":       ("\n💻 code-server погашен.", "\n💻 code-server is stopped."),
    "card.codestart":    ("💻 code-server", "💻 code-server"),
    # What the feature list becomes once a feature's card went to its topic,
    # and once a new feature was started: the menu, answered.
    "feat.topiclater":   ("\n\n⏳ Топик фичи пока не открылся — нажмите ещё раз чуть позже.",
                          "\n\n⏳ The feature's topic did not open yet — press again in a moment."),
    "feat.opened":       ("📌 <b>%(slug)s</b> — карточка в топике фичи.",
                          "📌 <b>%(slug)s</b> — the card is in the feature's topic."),
    "feat.newstarted":   ("✨ Новая фича в <b>%(repo)s</b> — вопросы придут сюда.",
                          "✨ A new feature in <b>%(repo)s</b> — its questions come here."),
    "feat.gone":         ("Фича <b>%(slug)s</b> больше не в работе.",
                          "Feature <b>%(slug)s</b> is no longer in progress."),
    "feat.continue":     ("▶️ Продолжить", "▶️ Continue"),
    # The same list of actions the checkbox opens in the terminal. There is no
    # checkbox here — there is nothing to press space with — so it gets a button
    # of its own.
    "feat.actions":      ("⚙️ Действия", "⚙️ Actions"),
    "feat.new":          ("✨ Новая фича", "✨ New feature"),
    # The state of a step's session. "Waiting" is blocked: claude has asked for
    # permission or put a question, and without an answer the step will not
    # move. It matters to a person to tell it from "working": the first needs
    # them right now, the second does not.
    "feat.working":      ("\n\n🟢 Шаг идёт — разговор в приложении Claude.",
                          "\n\n🟢 The step is running — the conversation is in "
                          "the Claude app."),
    "feat.blocked":      ("\n\n🟡 Шаг ждёт ответа — откройте приложение Claude.",
                          "\n\n🟡 The step is waiting for you — open the Claude "
                          "app."),
    "feat.idle":         ("\n\n⚪ Сессия шага открыта, но простаивает.",
                          "\n\n⚪ The step's session is open but idle."),
    "feat.nosession":    ("\n\n⚫ Шаг не запущен.", "\n\n⚫ The step is not running."),
    "feat.started":      ("Запускаю шаг <b>%(step)s</b> — разговор откроется в "
                          "приложении Claude.",
                          "Starting step <b>%(step)s</b> — the conversation "
                          "opens in the Claude app."),
    "feat.busy":         ("Шаг уже открыт в другом месте. Продолжайте там же — "
                          "два разговора об одном шаге разойдутся.",
                          "The step is already open elsewhere. Carry on there — "
                          "two conversations about one step would diverge."),

    # a question from sclaude
    "ask.title":         ("<b>%(repo)s</b> спрашивает:\n\n%(prompt)s",
                          "<b>%(repo)s</b> is asking:\n\n%(prompt)s"),
    "ask.context":       ("<pre>%(body)s</pre>\n\n", "<pre>%(body)s</pre>\n\n"),
    "ask.yes":           ("✅ Да", "✅ Yes"),
    "ask.no":            ("❌ Нет", "❌ No"),
    "ask.text":          ("Ответьте сообщением.", "Reply with a message."),
    # What the question's message becomes once it is answered, wherever from:
    # the question and its answer, without buttons.
    "ask.answered":      ("<b>%(repo)s</b>: <i>%(prompt)s</i>\n<b>%(reply)s</b>",
                          "<b>%(repo)s</b>: <i>%(prompt)s</i>\n<b>%(reply)s</b>"),
    "ask.by.terminal":   ("ответ из терминала", "answered in the terminal"),
    # The question may have closed while the person was thinking: it was
    # answered in the terminal, or its session ended. Staying silent about that
    # will not do — otherwise it is unclear why the button did nothing.
    # Text typed in the main chat while the open questions are in topics.
    "ask.intopic":       ("Открытые вопросы — в топиках фич. Ответьте там; "
                          "если топик удалён, откройте фичу из списка.",
                          "The open questions are in the features' topics. Answer "
                          "there; if a topic was deleted, open the feature from "
                          "the list."),
    "ask.which":         ("Открытых вопросов здесь несколько — ответьте на нужный "
                          "через «Ответить» на его сообщении.",
                          "Several questions are open here — answer one with "
                          "\u201cReply\u201d on its message."),
    "ask.nooption":      ("Такого варианта в списке нет — выберите номер из него.",
                          "The list has no such option — pick a number from it."),
    # Text typed for a question the orchestrator has laid out but the bot has
    # not shown yet: it is not closed, it is on its way.
    "ask.notyet":        ("Вопрос сейчас придёт — ответьте на него.",
                          "The question is on its way — answer it once it shows."),
    "ask.gone":          ("Этот вопрос уже закрыт.",
                          "That question is already closed."),
    # What a message with buttons becomes when it can no longer be deleted:
    # Telegram lets a bot delete only for 48 hours, and editing is the rest.
    "msg.stale":         ("⏹ <i>Больше не актуально.</i>",
                          "⏹ <i>No longer relevant.</i>"),
    "ask.pick":          ("Выберите пункт номером в ответном сообщении.",
                          "Reply with the number of the item you want."),

    # forgotten hard holders
    "idle.warn":         ("🌙 Держим непрерывно с <b>%(since)s</b> (%(held)s), "
                          "но следов работы нет (%(idle)s без ввода).\n\n"
                          "Держат:\n%(who)s\n\n"
                          "Первая причина — главная: пока она есть, ноутбук "
                          "не уснёт, даже если убрать остальные.",
                          "🌙 Held continuously since <b>%(since)s</b> "
                          "(%(held)s), with no sign of work (%(idle)s without "
                          "input).\n\nHeld by:\n%(who)s\n\n"
                          "The first one is the one that matters: while it "
                          "stands the laptop will not sleep, even with the "
                          "rest gone."),
    "idle.keep":         ("✋ Продолжать удерживать", "✋ Keep holding"),
    "idle.sleep":        ("😴 Усыпить как обычно", "😴 Let it sleep now"),
    "idle.kept":         ("✋ Хорошо, держим дальше.", "✋ Fine, still holding."),
    "idle.slept":        ("😴 Удержание снято — ноутбук уснёт по обычным "
                          "правилам Windows.",
                          "😴 Hold released — the laptop will sleep by the "
                          "usual Windows rules."),

    # sleep
    "sleep.warn":        ("⏰ Ноутбук уснёт в <b>%(at)s</b> (через %(min)d мин).\n\n"
                          "%(why)s\n\n"
                          "<i>Дальше Windows заснёт сама, минут через 15 "
                          "простоя. Продлить — кнопкой ниже.</i>",
                          "⏰ The laptop sleeps at <b>%(at)s</b> (in %(min)d min).\n\n"
                          "%(why)s\n\n"
                          "<i>Windows then sleeps on its own, after about 15 "
                          "minutes idle. Extend with the button below.</i>"),
    # Why things are heading for sleep — the cases differ, and it matters to a
    # person which one it is.
    "why.nobody":        ("Держать больше некому: ни SSH-сессий, ни сессии "
                          "code-server, ни трафика в tailnet, ни запущенного "
                          "claude или dev-сервера. Час с последнего из них "
                          "истекает.",
                          "Nothing is holding it any more: no SSH sessions, no "
                          "code-server session, no tailnet traffic, no running "
                          "claude or dev server. The hour since the last one "
                          "is running out."),
    "why.soft":          ("Держат только мягкие: %(who)s. Они дают час с "
                          "последней активности — этот час и истекает. "
                          "Жёстких (SSH, сессия code-server, трафик в tailnet), "
                          "которые не дают уснуть вовсе, сейчас нет.",
                          "Only soft holders are left: %(who)s. They give an "
                          "hour from the last activity, and that hour is "
                          "running out. There are no hard holders (SSH, a "
                          "code-server session, tailnet traffic), which would "
                          "prevent sleep entirely."),
    "why.refused":       ("Вы попросили дать ноутбуку уснуть, и удержание "
                          "снято, хотя держатели ещё есть: %(who)s.",
                          "You asked to let the laptop sleep, so the hold was "
                          "released even though holders are still around: "
                          "%(who)s."),
    "sleep.extend":      ("☕ Продлить на час", "☕ Add an hour"),
    "sleep.let":         ("😴 Пусть спит", "😴 Let it sleep"),
    "sleep.extended":    ("☕ Продлено до <b>%(at)s</b>.",
                          "☕ Extended until <b>%(at)s</b>."),
    "sleep.accepted":    ("😴 Хорошо, ноутбук уснёт как обычно.",
                          "😴 Fine, the laptop will sleep as usual."),
    "sleep.stale":       ("Это сообщение устарело", "This message is out of date"),
    "sleep.staletext":   ("⏰ <i>Сообщение устарело.</i>",
                          "⏰ <i>Message is out of date.</i>"),
    "extended.plain":    ("Продлено до <b>%(at)s</b>.",
                          "Extended until <b>%(at)s</b>."),

    # holders
    "hold.hard":         ("🔒 Идёт удалённая работа — сна не будет, пока это так.\n"
                          "Держат: %(who)s.",
                          "🔒 Remote work in progress — no sleep while that "
                          "holds.\nHeld by: %(who)s."),
    "hold.ssh":          ("SSH", "SSH"),
    "hold.code":         ("сессия code-server", "code-server session"),
    "hold.codesrv":      ("служба code-server", "code-server service"),
    "hold.tailnet":      ("трафик в tailnet", "tailnet traffic"),
    "hold.dev":          ("dev-сервер", "dev server"),
    "hold.sclaude":      ("шаг sclaude", "an sclaude step"),
    "hold.vscode":       ("открытый VS Code", "VS Code open"),
    "hold.claude":       ("Claude Code", "Claude Code"),
    "hold.nobody":       ("никто", "nobody"),
    "hold.manual":       ("ваше удержание до %(at)s",
                          "your hold until %(at)s"),

    # miscellaneous
    # No <pre>: a monospace block in Telegram is a "copy" button, and status is
    # not the sort of text anyone pastes anywhere. The traffic light rests on
    # emoji rather than alignment, so columns are not needed here.
    "status.title":      ("<b>Состояние keepawake</b>\n\n%(body)s",
                          "<b>keepawake status</b>\n\n%(body)s"),
    "cmd.unknown":       ("Не знаю такой команды. /menu",
                          "Unknown command. /menu"),
    "cmd.empty":         ("(пусто)", "(empty)"),
    "cmd.timeout":       ("команда не ответила за %(sec)d с",
                          "command did not answer in %(sec)d s"),
    "cmd.error":         ("ошибка: %(err)s", "error: %(err)s"),
    # The starts of sclaude's options that mean a refusal: "Go back" in the
    # action list, "none, go back" in the feature picker. Matched, not shown,
    # and in both languages at once — the bot does not know which one a list
    # was drawn in. sclaude prints English today.
    "option.back":       ("назад", "go back"),
    "option.none":       ("ничего", "none, go back"),
}

_lang = DEFAULT


def normalize(code):
    # Telegram sends "ru", "ru-RU", "en-GB". Only the first segment interests
    # us, and only one of those is special.
    #
    # English by default: Russian is switched on by an explicit sign rather than
    # by an absence of data. A client that did not report a language is most
    # likely not Russian — and if it is, the very first press will fix that.
    if not code:
        return DEFAULT
    return "ru" if str(code).split("-")[0].lower() == "ru" else "en"


def set_lang(code):
    global _lang
    _lang = normalize(code)
    return _lang


def current():
    return _lang


def t(key, **kw):
    pair = STRINGS.get(key)
    if not pair:
        return key          # a missing string must not bring the bot down
    text = pair[0] if _lang == "ru" else pair[1]
    return (text % kw) if kw else text


def ssh_holders(n):
    # Russian needs three forms, English two. A separate function, because
    # that does not fit into the dictionary.
    if _lang == "ru":
        if n % 10 == 1 and n % 100 != 11:
            return "%d SSH-сессия" % n
        if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return "%d SSH-сессии" % n
        return "%d SSH-сессий" % n
    return "%d SSH session%s" % (n, "" if n == 1 else "s")
