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
    "menu.chrome":       ("🌐 Chrome", "🌐 Chrome"),
    "menu.sclaude":      ("📋 Sclaude", "📋 Sclaude"),
    "menu.code":         ("💻 Code-server", "💻 Code-server"),
    "menu.settings":     ("⚙️ Настройки", "⚙️ Settings"),
    # The menu in the chat: the way to the Mini App, or, while phone access
    # is off, what has to work without it.
    "menu.inapp":        ("<b>%(host)s</b>\nМеню — в приложении.",
                          "<b>%(host)s</b>\nThe menu is in the app."),
    "menu.open":         ("☰ Открыть меню", "☰ Open the menu"),
    "menu.offline":      ("<b>%(host)s</b>\nДоступ с телефона выключен, и меню-приложение "
                          "не откроется. Здесь — удержание и включение доступа (или /phone).",
                          "<b>%(host)s</b>\nPhone access is off, so the menu app will "
                          "not open. Here: the hold, and turning access on (or /phone)."),
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
    "cmd.phone":         ("Включить доступ с телефона — меню-приложение",
                          "Turn phone access on — the menu app"),
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
    # "Until a time" on the menu page, which has a time field of its own.
    "awake.askpage":     ("До которого часа не спать? Время сегодняшнее; если оно "
                          "уже прошло — завтрашнее.",
                          "Until what time should it stay awake? Today's time; "
                          "one already past means tomorrow."),
    "awake.badtimepage": ("Не понял время — нужно <code>ЧЧ:ММ</code>.",
                          "I did not understand that time — it takes <code>HH:MM</code>."),
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
    "chrome.title":      ("<b>chrome-debug</b>\n%(state)s\n%(proxy)s\n\n"
                          "<i>«Ноутбук» открывает список фич в Chrome на ноутбуке, "
                          "«Телефон» — здесь. Сами фичи — в их карточках (Sclaude). "
                          "Отладочный порт %(port)s.</i>",
                          "<b>chrome-debug</b>\n%(state)s\n%(proxy)s\n\n"
                          "<i>\u201cLaptop\u201d opens the list of features in Chrome on "
                          "the laptop, \u201cPhone\u201d opens it here. The features "
                          "themselves are on their cards (Sclaude). Debug port %(port)s.</i>"),
    "chrome.running":    ("✅ работает", "✅ running"),
    "chrome.stopped":    ("⏹ остановлена", "⏹ stopped"),
    "chrome.proxyup":    ("✅ sclaude-proxy отвечает на :3000",
                          "✅ sclaude-proxy answering on :3000"),
    "chrome.proxydown":  ("⏹ sclaude-proxy не отвечает — фичи не открыть",
                          "⏹ sclaude-proxy is not answering — features cannot be opened"),
    "chrome.open":       ("🌐 Ноутбук", "🌐 Laptop"),
    "chrome.featstop":   ("⏹ Остановить", "⏹ Stop"),
    "chrome.phoneopen":  ("📲 Телефон", "📲 Phone"),
    "chrome.gatedown":   ("🔒 <b>Доступ с телефона выключен.</b> Меню-приложение и "
                          "кнопки 📲 не откроются. /menu оставляет здесь удержание, "
                          "/phone включает доступ обратно.",
                          "🔒 <b>Phone access is off.</b> The menu app and the 📲 "
                          "buttons will not open. /menu keeps the hold here, and /phone "
                          "turns access back on."),
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
    "svc.docs":          ("📖 Инструкции", "📖 Instructions"),
    "svc.lang":          ("🌍 Язык", "🌍 Language"),
    "svc.phoneon":       ("📲 Доступ с телефона: включён", "📲 Phone access: on"),
    "svc.phoneoff":      ("🔒 Доступ с телефона: выключен", "🔒 Phone access: off"),
    "svc.phonewait":     ("⏳ <b>Включаю доступ с телефона.</b> Жду, пока Tailscale "
                          "опубликует адрес в интернете, — обычно несколько минут. "
                          "Это сообщение изменится, когда всё будет готово; до тех пор "
                          "приложение не откроется.",
                          "⏳ <b>Turning phone access on.</b> Waiting for Tailscale to "
                          "publish the address on the internet — usually a few minutes. "
                          "This message changes when it is ready; until then the app "
                          "will not open."),
    "svc.phonestill":    ("⏳ Доступ уже включается: жду, пока Tailscale опубликует адрес. "
                          "Сообщение выше изменится, когда всё будет готово.",
                          "⏳ Phone access is already turning on: waiting for Tailscale to "
                          "publish the address. The message above changes when it is ready."),
    "svc.phoneready":    ("📲 <b>Доступ с телефона включён.</b>\n"
                          "• <b>☰ Menu</b> у поля ввода открывает меню-приложение;\n"
                          "• <b>📲 Открыть в приложении</b> на карточке фичи открывает его "
                          "сразу на этой фиче;\n"
                          "• кнопки 📲 открывают страницу фичи и code-server прямо в Telegram.\n"
                          "Пускает только вас.",
                          "📲 <b>Phone access is on.</b>\n"
                          "• <b>☰ Menu</b> by the input box opens the menu app;\n"
                          "• <b>📲 Open in the app</b> on a feature's card opens it on "
                          "that feature;\n"
                          "• the 📲 buttons open a feature's page and code-server right "
                          "in Telegram.\n"
                          "Only you are let in."),

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
    # The menu page (an experiment) asks before phone access goes: the page
    # itself goes through it.
    "svc.phoneoffask":   ("Выключить доступ с телефона? Это приложение закроется — "
                          "снова включить можно будет только из чата.",
                          "Turn phone access off? This app closes with it, and it "
                          "can be turned back on only from the chat."),
    "svc.phoneoffyes":   ("🔒 Выключить", "🔒 Turn off"),
    "svc.restart":       ("🔁 Перезапуск демона", "🔁 Restart daemon"),
    "svc.restarting":    ("🔁 Перезапускаюсь…\nСообщу, когда поднимусь.",
                          "🔁 Restarting…\nI will report once I am back."),
    "svc.restarted":     ("✅ Демон перезапущен и снова на связи.",
                          "✅ Daemon restarted and back online."),
    # The menu page waited a minute and the bot did not come back.
    "svc.notback":       ("⚠️ Демон не вернулся за минуту.\n"
                          "На ноутбуке: <code>journalctl --user -u %(unit)s</code>",
                          "⚠️ The daemon is not back after a minute.\n"
                          "On the laptop: <code>journalctl --user -u %(unit)s</code>"),

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
    # On the menu page, which has no laptop link: only the button brings it up.
    "code.stoppedpage":  ("⏹ погашен — ▶️ поднимает его", "⏹ down — ▶️ brings it up"),
    # The same on the menu page, where the gate's button opens it.
    "code.titlepage":    ("<b>code-server</b>\n%(state)s\n%(folder)s\n%(password)s\n\n"
                          "<i>Гаснет сам после часа простоя.</i>",
                          "<b>code-server</b>\n%(state)s\n%(folder)s\n%(password)s\n\n"
                          "<i>Stops by itself after an hour idle.</i>"),
    # Only on the menu page: a page is not kept in the chat's history.
    "code.password":     ("Пароль: <code>%(pw)s</code>", "Password: <code>%(pw)s</code>"),
    "code.nopassword":   ("Пароль — в ~/.config/code-server/config.yaml",
                          "The password is in ~/.config/code-server/config.yaml"),
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
    "chrome.featpage":   ("<b>chrome-debug</b>\n%(state)s\n\n🖥 <b>%(slug)s</b>: %(dev)s\n\n"
                          "<i>Открыть фичу в Chrome на ноутбуке или здесь; остановленная "
                          "поднимется сама. Запуск и остановка dev-сервера — в её карточке "
                          "(Sclaude).</i>",
                          "<b>chrome-debug</b>\n%(state)s\n\n🖥 <b>%(slug)s</b>: %(dev)s\n\n"
                          "<i>Open the feature in the laptop's Chrome or here; a stopped one "
                          "starts by itself. Starting and stopping its dev server is on its "
                          "card (Sclaude).</i>"),
    "chrome.featnodev":  ("dev-сервера ещё нет", "no dev server yet"),
    "menu.here":         ("\n📍 %(slug)s", "\n📍 %(slug)s"),
    "menu.otherhome":    ("📍 Другая фича", "📍 Another feature"),
    "menu.choosehome":   ("📍 Выбрать фичу", "📍 Choose a feature"),
    "menu.pickhome":     ("На какой фиче стоять? Sclaude, Chrome и Code-server будут о ней.",
                          "Which feature should the menu stand on? Sclaude, Chrome and "
                          "Code-server will be about it."),
    "menu.machine":      ("💻 Весь ноутбук", "💻 The whole machine"),
    "card.devpage":      ("\n\n🖥 Dev-сервер: %(state)s", "\n\n🖥 Dev server: %(state)s"),
    "card.codepage":     ("\n💻 code-server запущен.", "\n💻 code-server is running."),
    "card.phonelink":    ("с телефона", "from the phone"),
    "card.nodev":        ("\n\n🖥 Dev-сервера у фичи ещё нет.",
                          "\n\n🖥 The feature has no dev server yet."),
    "card.code":         ("\n💻 code-server: <a href=\"%(url)s\">открыть worktree</a> · "
                          "<code>%(local)s</code>",
                          "\n💻 code-server: <a href=\"%(url)s\">open the worktree</a> · "
                          "<code>%(local)s</code>"),
    "card.nocode":       ("\n💻 code-server погашен.", "\n💻 code-server is stopped."),
    "card.codestart":    ("💻 code-server", "💻 code-server"),
    # Mini App buttons (an experiment): the menu page on this feature, and
    # code-server through the gate, without Tailscale on the phone.
    "card.app":          ("📲 Открыть в приложении", "📲 Open in the app"),
    "code.app":          ("📲 code-server здесь", "📲 code-server here"),
    # What the feature list becomes once a feature's card went to its topic,
    # and once a new feature was started: the menu, answered.
    "feat.topiclater":   ("\n\n⏳ Топик фичи пока не открылся — нажмите ещё раз чуть позже.",
                          "\n\n⏳ The feature's topic did not open yet — press again in a moment."),
    "feat.opened":       ("📌 <b>%(slug)s</b> — карточка в топике фичи.",
                          "📌 <b>%(slug)s</b> — the card is in the feature's topic."),
    # A new feature's topic before it has a name, and what the menu says.
    "feat.newtopic":     ("✨ Новая фича · %(repo)s", "✨ New feature · %(repo)s"),
    "feat.newtopicat":   ("✨ Новая фича в <b>%(repo)s</b> — вопросы придут в её топик.",
                          "✨ A new feature in <b>%(repo)s</b> — its questions come to its topic."),
    "feat.newstarted":   ("✨ Новая фича в <b>%(repo)s</b> — вопросы придут сюда.",
                          "✨ A new feature in <b>%(repo)s</b> — its questions come here."),
    "feat.gone":         ("Фича <b>%(slug)s</b> больше не в работе.",
                          "Feature <b>%(slug)s</b> is no longer in progress."),
    # The card's buttons on the menu page, where they stand without the
    # card's lines beside them: each says what it acts on.
    "page.onlaptop":     ("🌐 Открыть браузер на ноутбуке", "🌐 Open the browser on the laptop"),
    "page.closechrome":  ("⏹ Закрыть Chrome", "⏹ Close Chrome"),
    "page.onphone":      ("📲 Показать приложение на телефоне", "📲 Show app on Phone"),
    "page.continue":     ("▶️ Продолжить шаг", "▶️ Continue the step"),
    "page.continuestep": ("▶️ Продолжить шаг %(step)s", "▶️ Continue step %(step)s"),
    "page.finish":       ("⏩ Дальше: preview → QA → merge", "⏩ Next: preview → QA → merge"),
    "page.actions":      ("⚙️ Другие действия с фичей", "⚙️ Other feature actions"),
    "page.devstop":      ("⏹ Остановить dev-сервер", "⏹ Stop the dev server"),
    "page.devstart":     ("▶️ Запустить dev-сервер", "▶️ Start the dev server"),
    "page.refresh":      ("🔄 Обновить карточку", "🔄 Refresh the card"),
    # The feature's actions on the menu page, grouped by where each leads.
    "act.title":         ("⚙️ <b>Действия с фичей</b> %(slug)s", "⚙️ <b>Feature actions</b> %(slug)s"),
    "act.steps":         ("план · код · PR · ревью · с main · после merge · ретро",
                          "plan · code · PR · review · with main · after the merge · retro"),
    "act.now":           ("Сейчас: <b>%(step)s</b>", "Now: <b>%(step)s</b>"),
    "act.back":          ("⏪ Назад, к шагу %(n)s", "⏪ Back to step %(n)s"),
    "act.reopen":        ("⏪ Заново открыть шаг %(n)s", "⏪ Reopen step %(n)s"),
    "act.stay":          ("🔁 На текущем шаге", "🔁 On the current step"),
    "act.forward":       ("⏩ Вперёд", "⏩ Forward"),
    "act.after":         ("🧹 После merge", "🧹 After the merge"),
    "act.end":           ("🗑 Закончить фичу", "🗑 End the feature"),
    "act.cancel":        ("‹ Ничего не делать", "‹ Do nothing"),
    "act.map":           ("🗺 Карта процесса", "🗺 Process map"),
    "card.mapready":     ("🗺 Dev-сервер запускается — карта процесса открывается кнопкой ниже.",
                          "🗺 The dev server is starting — the process map opens from the button below."),
    "card.mapfailed":    ("🗺 У фичи ещё нет адреса: dev-сервер не успел его получить. Нажми ещё раз через минуту.",
                          "🗺 The feature has no address yet: its dev server has not claimed one. Press again in a minute."),
    "page.answered":     ("✅ Ответ: %(reply)s", "✅ Answered: %(reply)s"),
    "page.waiting":      ("sclaude ещё не спросил. Через пару секунд — «Обновить».",
                          "sclaude has not asked yet. Give it a few seconds, then Refresh."),
    "page.gone":         ("На этот вопрос уже ответили — в терминале или в чате.",
                          "This question was already answered — in the terminal or the chat."),
    "page.typed":        ("Этот вопрос ждёт ответа текстом: ответьте в топике фичи.",
                          "This question takes a typed answer: answer it in the feature's topic."),
    "page.question":     ("🔄 Обновить", "🔄 Refresh"),
    "page.tocard":       ("‹ К карточке", "‹ Back to the card"),
    "feat.continue":     ("▶️ Продолжить", "▶️ Continue"),
    # The same list of actions the checkbox opens in the terminal. There is no
    # checkbox here — there is nothing to press space with — so it gets a button
    # of its own.
    "feat.actions":      ("⚙️ Действия", "⚙️ Actions"),
    "feat.new":          ("✨ Новая фича", "✨ New feature"),
    # The review's keys on the topic's message that a pass or a fix session
    # started (review_keys.py): the terminal's [s] and [x x].
    "rv.last.pass":      ("⏭ Последний проход за новыми замечаниями",
                          "⏭ Last pass for new findings"),
    "rv.last.round":     ("⏭ Последний раунд: дальше только проверка фиксов",
                          "⏭ Last round: then only check the fixes"),
    "rv.back":           ("↩️ Отменить: искать дальше", "↩️ Take it back: keep searching"),
    "rv.stop":           ("⏹ Остановить сейчас", "⏹ Stop now"),
    "rv.stop.yes":       ("⏹ Да, остановить и отбросить этот проход",
                          "⏹ Yes, stop and drop this pass"),
    "rv.stop.no":        ("▶️ Пусть идёт", "▶️ Carry on"),
    "rv.pass.ok":        ("Этот проход — последний, кто ищет новое",
                          "This pass is the last to look for new findings"),
    "rv.round.ok":       ("После этой сессии ревью только проверит фиксы",
                          "After this session the review only checks the fixes"),
    "rv.back.ok":        ("Отменено: ревью ищет дальше", "Taken back: the review keeps searching"),
    "rv.now":            ("Проход останавливается; открытое уйдёт в сессию ревью",
                          "Stopping the pass; what is open goes to the review session"),
    "rv.gone":           ("Это ревью уже закончилось", "That review has ended"),
    "rv.failed":         ("Не получилось передать sclaude — попробуйте ещё раз",
                          "Could not pass it to sclaude — try again"),
    # The project's .sclaude/config.json, as `sclaude config` shows it. The
    # explanations themselves are sclaude's, from config.example.json.
    "cfg.button":        ("🧩 Конфиг проекта", "🧩 Project config"),
    "cfg.title":         ("🧩 <b>%(repo)s</b> — <code>.sclaude/config.json</code>\n"
                          "⚙️ — выбирается здесь; остальное правится в файле.",
                          "🧩 <b>%(repo)s</b> — <code>.sclaude/config.json</code>\n"
                          "⚙️ — set here; the rest is edited in the file."),
    "cfg.nofile":        ("\n\nФайла ещё нет: <code>sclaude new</code> предложит его написать — "
                          "из того, что найдёт в репозитории.",
                          "\n\nThere is no file yet: <code>sclaude new</code> offers to write one "
                          "from what it finds in the repository."),
    "cfg.setting":       ("⏳ Меняю…", "⏳ Setting it…"),
    "cfg.toolong":       ("<i>Имя репозитория не помещается в кнопку Telegram — выберите "
                          "значение в терминале: <code>sclaude config</code>.</i>",
                          "<i>The repository name does not fit in a Telegram button — set "
                          "it at the terminal: <code>sclaude config</code>.</i>"),
    "cfg.writefirst":    ("<i>Выбирается здесь, когда у проекта есть конфиг: файл из одной "
                          "секции <code>sclaude new</code> принял бы за готовый и не предложил бы "
                          "написать остальное.</i>",
                          "<i>Set here once the project has a config: a file of one section "
                          "would pass with <code>sclaude new</code> for a finished one, and it would "
                          "never offer to write the rest.</i>"),
    "cfg.setpartly":     ("⚠️ %(section)s: <b>%(value)s</b> записан, но sclaude не закончил "
                          "то, что за этим следует (Actions для review) — журнал бота "
                          "скажет, что осталось.",
                          "⚠️ %(section)s: <b>%(value)s</b> is written, but sclaude did not "
                          "finish what follows it (Actions, for review) — the bot's log "
                          "says what is left."),
    "cfg.broken":        ("\n\n⚠️ Файл не читается как JSON — здесь ничего не изменится, "
                          "пока его не поправят.",
                          "\n\n⚠️ The file does not read as JSON — nothing changes here "
                          "until it is fixed."),
    "cfg.torepo":        ("‹ К репозиторию", "‹ The repository"),
    "cfg.tolist":        ("‹ Все секции", "‹ All sections"),
    "cfg.unknown":       ("Эту секцию sclaude не читает.", "sclaude does not read this section."),
    "cfg.now":           ("Сейчас:", "Now:"),
    "cfg.notset":        ("<i>Не задано.</i>", "<i>Not set.</i>"),
    "cfg.commit":        ("<i>Файл — проекта: изменение остаётся в рабочем дереве основного "
                          "checkout, закоммитьте его там.</i>",
                          "<i>The file is the project's: a change stays in the main "
                          "checkout's working tree — commit it there.</i>"),
    "cfg.infile":        ("<i>Правится в файле — в терминале <code>sclaude config</code> открывает его "
                          "последней строкой.</i>",
                          "<i>Edited in the file — at the terminal the last row of "
                          "<code>sclaude config</code> opens it.</i>"),
    "cfg.set":           ("✅ %(section)s: <b>%(value)s</b> — в конфиге проекта.",
                          "✅ %(section)s: <b>%(value)s</b> — in the project's config."),
    "cfg.same":          ("%(section)s уже <b>%(value)s</b>.", "%(section)s is <b>%(value)s</b> already."),
    "cfg.notchanged":    ("⚠️ %(section)s не изменён — подробности в журнале бота.",
                          "⚠️ %(section)s not changed — the bot's log says why."),
    # A new feature on the menu page: the terminal's picker, with buttons.
    "nf.title":          ("✨ <b>Новая фича</b> в %(repo)s\nИз открытой issue или по имени.",
                          "✨ <b>A new feature</b> in %(repo)s\nFrom an open issue or by a name."),
    "nf.noissues":       ("\n\nОткрытых issues GitHub не назвал — или gh недоступен.",
                          "\n\nGitHub named no open issues — or gh is not reachable."),
    "nf.noanswer":       ("\n\n⚠️ GitHub не ответил — список issues недоступен. «Обновить» "
                          "спросит ещё раз; по имени можно начать и так.",
                          "\n\n⚠️ GitHub did not answer — the issues are not to hand. "
                          "Refresh asks again; a name starts without them."),
    "nf.noconfig":       ("<i>У проекта нет .sclaude/config.json: после старта sclaude "
                          "спросит в чате, записать ли его.</i>",
                          "<i>The project has no .sclaude/config.json: after the start "
                          "sclaude asks in the chat whether to write it.</i>"),
    "nf.more":           ("\n\nЕщё %(n)d не поместились — их можно начать из терминала.",
                          "\n\n%(n)d more did not fit — start them from the terminal."),
    "nf.byname":         ("✏️ Ввести имя", "✏️ Type a name"),
    "nf.bynamehint":     ("issue можно создать по нему", "an issue can be made from it"),
    "nf.mine":           ("Назначены мне", "Assigned to me"),
    "nf.other":          ("Остальные открытые", "Other open issues"),
    "nf.blockedby":      ("⛔ ждёт %(by)s", "⛔ blocked by %(by)s"),
    "nf.gone":           ("Issue #%(n)s больше не открыта.", "Issue #%(n)s is no longer open."),
    "nf.issue":          ("✨ <b>#%(n)d</b> %(title)s", "✨ <b>#%(n)d</b> %(title)s"),
    "nf.blocked":        ("⛔ Её ждут открытые issues:", "⛔ It is blocked by open issues:"),
    "nf.blockednote":    ("<i>План опирается на то, чего ещё нет. Начать можно и так — "
                          "иногда фича как раз их и заканчивает.</i>",
                          "<i>Its plan leans on work that has not landed. It can start "
                          "anyway — sometimes the feature is what finishes them.</i>"),
    "nf.branchnote":     ("Имя ветки — по номеру и заголовку; поправьте, если нужно. Ветка "
                          "будет <code>feat/&lt;имя&gt;</code>.",
                          "The branch name comes from the number and the title; correct it "
                          "if need be. The branch is <code>feat/&lt;name&gt;</code>."),
    "nf.branch":         ("имя ветки", "branch name"),
    "nf.start":          ("▶️ Начать", "▶️ Start"),
    "nf.startanyway":    ("▶️ Всё равно начать", "▶️ Start anyway"),
    "nf.tolist":         ("‹ К списку issues", "‹ The issues"),
    "nf.named":          ("✏️ <b>Новая фича</b> в %(repo)s по имени. Из имени — ветка "
                          "<code>feat/&lt;имя&gt;</code> и, если отмечено, заголовок issue.",
                          "✏️ <b>A new feature</b> in %(repo)s by a name. The name makes "
                          "the branch <code>feat/&lt;name&gt;</code> and, when ticked, the "
                          "issue's title."),
    "nf.name":           ("имя фичи", "feature name"),
    "nf.createissue":    ("Создать issue на GitHub", "Create a GitHub issue"),
    "nf.createyes":      ("с этим заголовком, назначенную вам",
                          "with this title, assigned to you"),
    "nf.createno":       ("фича начнётся без issue — шагу 1 нечего прочесть",
                          "the feature starts without one — step 1 has nothing to read"),
    "nf.badname":        ("В имени нужна хотя бы одна латинская буква или цифра.",
                          "A name needs at least one Latin letter or digit."),
    "nf.exists":         ("Ветка или каталог <b>%(slug)s</b> уже есть — продолжите ту фичу "
                          "или выберите другое имя.",
                          "A branch or directory <b>%(slug)s</b> exists already — continue "
                          "that feature or choose another name."),
    "nf.startedtopic":   ("✨ <b>%(slug)s</b> в <b>%(repo)s</b> начата — вопросы придут в "
                          "её топик.",
                          "✨ <b>%(slug)s</b> in <b>%(repo)s</b> has started — its questions "
                          "come to its topic."),
    "nf.started":        ("✨ <b>%(slug)s</b> в <b>%(repo)s</b> начата — вопросы придут сюда.",
                          "✨ <b>%(slug)s</b> in <b>%(repo)s</b> has started — its questions "
                          "come here."),
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
    "feat.cache":        ("\n💾 Кэш сессии: ещё %(m)s мин.",
                          "\n💾 Session cache: %(m)s min left."),
    "feat.cachegone":    ("\n💾 Кэш сессии истёк: следующий запрос запишет его заново.",
                          "\n💾 The session cache has expired: the next request writes it again."),
    "feat.idle":         ("\n\n⚪ Сессия шага открыта, но простаивает.",
                          "\n\n⚪ The step's session is open but idle."),
    # No Claude session for the step is open: what that means depends on
    # whether a step is left — ▶️ opens one mid-step, and after the last there
    # is none to open.
    "feat.nosession":    ("\n\n⚫ Сессия Claude не открыта — ▶️ «Продолжить» её откроет.",
                          "\n\n⚫ No Claude session is open — ▶️ Continue opens one."),
    "feat.nosessiondone": ("\n\n⚫ Сессия Claude не открыта: шаги пройдены.",
                           "\n\n⚫ No Claude session is open: the steps are done."),
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
    # The menu page's notes under each screen: where one is, what the
    # buttons do, and what changes after them.
    "help.menu":         ("Всё, что можно сделать с ноутбуком с телефона. "
                          "💤 Keepawake — уснёт ли ноутбук. 📋 Sclaude — проекты и их фичи. "
                          "💻 Code-server — редактор. 🌐 Chrome — браузер на ноутбуке. "
                          "⚙️ Настройки — язык, доступ с телефона, сам бот.\n"
                          "Всё, что вы здесь запускаете, оставляет строку в чате.",
                          "Everything you can do with the laptop from the phone. "
                          "💤 Keepawake — whether the laptop sleeps. 📋 Sclaude — the "
                          "projects and their features. 💻 Code-server — the editor. "
                          "🌐 Chrome — the browser on the laptop. ⚙️ Settings — language, "
                          "phone access, the bot itself.\n"
                          "Whatever you start here leaves a line in the chat."),
    "help.keepawake":    ("Может ли ноутбук уснуть. Он не спит, пока его держит что-то из "
                          "списка ниже, и до срока, который вы дали здесь. ☕ — ещё столько "
                          "времени с этой минуты; 🕒 — до нужного часа; ♾ — пока не "
                          "отпустите сами; 🛑 — отпустить: Windows усыпит его по своему "
                          "таймеру простоя.",
                          "Whether the laptop may sleep. It stays awake while something in "
                          "the list below holds it, and until the deadline you give here. "
                          "☕ — that much more time from now; 🕒 — until a time of day; "
                          "♾ — until you release it yourself; 🛑 — release it: Windows "
                          "puts it to sleep on its own idle timer."),
    "help.until":        ("Ноутбук не уснёт до этого времени. Потом вернутся обычные "
                          "правила: держатели дают час с последней активности.",
                          "The laptop stays awake until this time. Then the usual rules "
                          "come back: holders give an hour from their last activity."),
    "help.code":         ("code-server — VS Code в браузере, работает на ноутбуке. "
                          "▶️ 🔄 ⏹ — запустить, перезапустить, остановить. 📲 открывает "
                          "его здесь, через шлюз бота: Tailscale на телефоне не нужен. "
                          "Открывает репозиторий, выбранный в Sclaude, спрашивает свой "
                          "пароль и сам гаснет после часа без дела.",
                          "code-server is VS Code in the browser, running on the laptop. "
                          "▶️ 🔄 ⏹ — start, restart, stop it. 📲 opens it here, through "
                          "the bot's gate: no Tailscale needed on the phone. It opens the "
                          "repository chosen in Sclaude, asks for its own password and "
                          "stops by itself after an hour unused."),
    "help.chrome":       ("Chrome с отладочным портом на ноутбуке — им Claude пользуется "
                          "для проверок. 🌐 «Ноутбук» открывает там список фич, 📲 "
                          "«Телефон» — тот же список здесь, ⏹ закрывает браузер. Страница "
                          "каждой фичи — в её карточке в Sclaude.",
                          "Chrome with a debug port on the laptop — what Claude uses for "
                          "its checks. 🌐 Laptop opens the list of features there, 📲 "
                          "Phone opens the same list here, ⏹ closes the browser. Each "
                          "feature's page is on its card in Sclaude."),
    "help.sclaude":      ("Фичи в работе в этом репозитории и шаг каждой. Фича открывает "
                          "свою карточку; ✨ запускает новую — её вопросы придут в её "
                          "собственный топик в чате; 🧩 — конфиг проекта. Выбранный здесь "
                          "репозиторий открывает и code-server.",
                          "The features in progress in this repository, each with its "
                          "step. A feature opens its card; ✨ starts a new one — its "
                          "questions come to a topic of its own in the chat; 🧩 is the "
                          "project's config. The repository chosen here is also the one "
                          "code-server opens."),
    "help.repos":        ("Какой репозиторий показывает Sclaude и открывает code-server. "
                          "Если code-server запущен, выбор другого перезапустит его на нём.",
                          "Which repository Sclaude shows and code-server opens. Choosing "
                          "another restarts a running code-server on it."),
    "help.card":         ("Одна фича. ▶️ «Продолжить» — sclaude берётся за текущий шаг; "
                          "⚙️ «Действия» — список того, что с ней можно сделать. Вопросы "
                          "и того и другого придут в топик фичи. Dev-сервер — её "
                          "запущенное приложение: 🌐 открывает его в Chrome на ноутбуке, "
                          "📲 — здесь, ▶️ ⏹ запускают и останавливают. Каждое действие "
                          "оставляет строку в топике фичи.",
                          "One feature. ▶️ Continue — sclaude takes up the current step; "
                          "⚙️ Actions — the list of what can be done with it. The "
                          "questions of both come to the feature's topic. The dev server "
                          "is its running app: 🌐 opens it in the laptop's Chrome, 📲 "
                          "here, ▶️ ⏹ start and stop it. Each action leaves a line in the "
                          "feature's topic."),
    "help.settings":     ("🌍 Язык бота и этого приложения. 📖 Инструкции — как устроен "
                          "keepawake. 🔁 Перезапуск — бот перезапустится и отчитается в "
                          "чате. Доступ с телефона открывает это приложение и кнопки 📲 из "
                          "интернета, пуская только вас; без него приложение закроется, и "
                          "в чате останется короткое меню.",
                          "🌍 The language of the bot and this app. 📖 Instructions — how "
                          "keepawake works. 🔁 Restart — the bot restarts and reports back "
                          "in the chat. Phone access opens this app and the 📲 buttons "
                          "from the internet, letting only you in; without it this app "
                          "closes and the chat keeps a short menu."),
    "help.lang":         ("На каком языке говорят бот и это приложение. Русский или "
                          "английский закрепляют выбор; «Как в Telegram» берёт язык "
                          "вашего приложения Telegram.",
                          "Which language the bot and this app speak. Russian or English "
                          "fixes the choice; Follow Telegram takes your Telegram app's "
                          "language."),
    "help.newfeat":      ("Как в терминале: свои issues сверху, у каждой — метки и то, "
                          "что её блокирует. Или имя, из которого будет и ветка, и issue.",
                          "As at the terminal: your own issues first, each with its labels "
                          "and what blocks it. Or a name, which makes the branch and the "
                          "issue."),
    "help.nfissue":      ("▶️ запускает sclaude на этой issue с этим именем ветки: дальше — "
                          "шаг 1, план, и его вопросы в топике фичи.",
                          "▶️ starts sclaude on this issue with this branch name: then step "
                          "1, the plan, with its questions in the feature's topic."),
    "help.nfname":       ("▶️ запускает sclaude с этим именем; галочка решает за него, "
                          "создавать ли issue — в чате он об этом не спросит.",
                          "▶️ starts sclaude with this name; the tick answers whether to "
                          "create an issue — it will not ask in the chat."),
    "help.config":       ("Конфиг проекта, как `sclaude config` в терминале: секция, что в "
                          "ней сейчас и зачем она. ⚙️ review, qa и merge выбираются здесь; "
                          "остальное — структуры, их правят в файле.",
                          "The project's config, as `sclaude config` shows it at the "
                          "terminal: each section, what it holds and what it is for. ⚙️ "
                          "review, qa and merge are set here; the rest are structures "
                          "edited in the file."),
    "help.docs":         ("Как устроен keepawake, по разделам.",
                          "How keepawake works, section by section."),
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
