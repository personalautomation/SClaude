#!/usr/bin/env python3
#
# The docs the bot prints: how to install everything from scratch, what the
# system is made of and what to do when it misbehaves.
#
# A separate module rather than part of i18n.py: that one holds short interface
# strings, while these are multi-line texts among which the short ones would be
# impossible to find. They are split into sections also because Telegram has a
# ceiling of 4096 bytes per message — this cannot be sent whole.
#
# The text has to survive a reinstall of the system six months from now, when
# the author no longer remembers why it was done this way. So there are not only
# commands here but reasons: why schtasks will not do, why the BOM is
# mandatory, why enable-linger must not be skipped.

SECTIONS = {
    'why': (
        '<b>🧩 Зачем что нужно</b>\n\nВсё вместе решает одну задачу: продолжать работу с телефона, пока ноутбук стоит закрытым дома.\n\n<b>Tailscale</b> — приватная сеть между вашими устройствами. Даёт ноутбуку постоянный адрес (<code>100.x.x.x</code>), который не меняется ни при перезапуске WSL, ни при смене WiFi, ни в другой стране. Без него пришлось бы пробрасывать порты через роутер и выставлять их в интернет; здесь ничего наружу не открыто — соединение видят только ваши устройства.\nВажно: стоит <b>внутри WSL</b>, поэтому адрес принадлежит Ubuntu, а не Windows.\n\n<b>Termius</b> — SSH-клиент на телефоне. Даёт настоящий терминал: стрелки, полноэкранные программы, всё как в обычной консоли. Именно поэтому <code>sclaude</code> и <code>claude</code> работают в нём полноценно, а в этом боте — нет.\n\n<b>code-server</b> — VS Code в браузере телефона. Когда терминала мало: файлы, поиск по проекту, вкладки, git. Терминал внутри тоже настоящий.\n\n<b>chrome-debug</b> — браузер на ноутбуке с открытым отладочным портом. Через него Claude Code видит вашу страницу: кликает, читает консоль, снимает скриншоты.\n\n<b>📲 Телефон в карточке фичи и в карточке chrome-debug</b> — фича прямо в Telegram, на весь экран и с адресной строкой, без Tailscale на телефоне. Работает, пока в Настройках включён доступ с телефона: <code>tailscale funnel</code> держит в интернете одну дверь, <code>sclaude-gate</code>, и пускает в неё только вас — по подписи Telegram. После включения Tailscale начинает пропускать через несколько минут — бывает, и через пять: пока доступ выключен, адреса нет в DNS интернета, и возвращается он не сразу. Бот пишет, что ждёт, и меняет это сообщение, когда приложение можно открыть.\n\n<b>keepawake</b> (этот бот) — то, что не даёт ноутбуку уснуть посреди всего перечисленного, и отпускает его, когда работа кончилась.\n\n<b>sclaude</b> — оркестратор разработки фичи: план, код, PR, ревью, каждый шаг своей моделью.',
        '<b>🧩 What each piece is for</b>\n\nTogether they solve one problem: keep working from a phone while the laptop sits closed at home.\n\n<b>Tailscale</b> — a private network between your own devices. It gives the laptop a permanent address (<code>100.x.x.x</code>) that survives a WSL restart, a WiFi change, another country. Without it you would forward ports through a router and expose them to the internet; here nothing is exposed — only your devices see the connection.\nNote: it runs <b>inside WSL</b>, so the address belongs to Ubuntu, not Windows.\n\n<b>Termius</b> — an SSH client on the phone. It gives a real terminal: arrow keys, full-screen programs, everything a console does. That is exactly why <code>sclaude</code> and <code>claude</code> work there in full and cannot work in this bot.\n\n<b>code-server</b> — VS Code in the phone browser. For when a terminal is not enough: files, project-wide search, tabs, git. Its built-in terminal is real too.\n\n<b>chrome-debug</b> — a browser on the laptop with the debugging port open. Through it Claude Code sees your page: clicks, reads the console, takes screenshots.\n\n<b>📲 Phone on a feature\'s card and on the chrome-debug card</b> — a feature right in Telegram, full screen and with an address bar, with no Tailscale on the phone. It works while phone access is on in Settings: <code>tailscale funnel</code> keeps one door on the internet, <code>sclaude-gate</code>, and lets only you through it — by the signature Telegram puts on the page. Once turned on, Tailscale starts carrying it within a few minutes — sometimes five: while it is off, the address is gone from public DNS, and it takes that long to come back. The bot says it is waiting, and changes that message when the app can open.\n\n<b>keepawake</b> (this bot) — the part that stops the laptop falling asleep in the middle of all that, and lets it go when the work is done.\n\n<b>sclaude</b> — an orchestrator for a feature cycle: plan, code, PR, review, each step with its own model.'),
    'usage': (
        '<b>📱 Как пользоваться</b>\n\n<b>Меню</b>\nКогда доступ с телефона включён (/phone или кнопка в /menu), <b>☰ Menu</b> у поля ввода открывает бота как приложение внутри Telegram — Tailscale на телефоне не нужен. Под каждым экраном строка о том, что это за экран. Всё, что вы там запускаете, оставляет строку 📱 в чате; вопросы sclaude приходят в чат виджетом, где каждый вариант — кнопка. Включение занимает несколько минут — бот напишет, когда всё готово. После перезагрузки ноутбука доступ снова выключен.\n/menu в чате даёт всё меню виджетом — и без доступа.\n\n<b>Управление сном</b>\n💤 <b>Keepawake</b> — кто держит и сколько осталось, и: час, четыре часа, сутки, до заданного времени, не спать вовсе — или наоборот, отпустить всё и спать как обычно. Время, уже прошедшее сегодня, считается завтрашним. Продление никогда не укорачивает уже имеющееся удержание; чтобы укоротить — «отпустить».\nЗа полчаса до сна бот спросит виджетом с отсчётом и объяснит, почему.\n\n<b>Фичи</b>\n📋 <b>Sclaude</b> — репозитории, их фичи с текущим шагом, ✨ новая фича и 🧩 конфиг проекта. В приложении новая фича начинается как в терминале: из открытой issue (свои сверху, с тем, что её блокирует) с правкой имени ветки — или по имени, с галочкой «создать issue». Конфиг — каждая секция <code>.sclaude/config.json</code> с объяснением; выбор кнопками остаётся на этом компьютере, вне git. Фича открывает свою карточку: шаг, ▶️ продолжить, ⚙️ действия, dev-сервер — 🌐 в Chrome на ноутбуке, 📲 прямо в приложении, ▶️/⏹ запустить или остановить — и 💻 code-server на её worktree. У каждой фичи свой топик: туда приходят её вопросы, а карточка там открывает приложение на этой фиче. На старте ревью там кнопки терминала: ⏭ последний проход, ⏹ стоп.\nОстановленная фича поднимается при открытии (около минуты), а та, которую полчаса никто не открывал, гаснет.\n🌐 <b>Chrome</b> — браузер ноутбука и список всех фич. 💻 <b>Code-server</b> — VS Code в браузере; 📲 открывает его в приложении.\n\n<b>Работа из терминала</b>\nС Tailscale на телефоне: <b>Termius</b> — хост <code>&lt;имя&gt;.ts.net</code>, порт 22, вход по ключу. Здесь работают <code>sclaude</code> и <code>claude</code>. Пока вы подключены, ноутбук не спит.\n\n<b>Язык</b>\nБот говорит на языке вашего клиента Telegram; ⚙️ Настройки → 🌍 Язык закрепляют другой, пока не вернёте «Как в Telegram».',
        '<b>📱 How to use it</b>\n\n<b>The menu</b>\nWith phone access on (/phone, or the button in /menu), <b>☰ Menu</b> by the input box opens the bot as an app inside Telegram — no Tailscale needed on the phone. Under each screen a line says what it is for. Whatever you start there leaves a 📱 line in the chat; questions from sclaude come to the chat as a widget where every option is a button. Turning access on takes a few minutes — the bot says when it is ready. After the laptop restarts, access is off again.\n/menu in the chat gives the whole menu as a widget — without access too.\n\n<b>Managing sleep</b>\n💤 <b>Keepawake</b> — who is holding and how long is left, and: one hour, four hours, one day, until a given time, never sleep — or the opposite, release every hold and sleep normally. A time already past today is read as tomorrow. Extending never shortens a hold you already have; to cut it short use “release”.\nHalf an hour before sleep the bot asks in a widget counting down, and explains why.\n\n<b>Features</b>\n📋 <b>Sclaude</b> — repositories, their features with the current step, ✨ new feature and 🧩 the project’s config. In the app a new feature starts as at the terminal: from an open issue (yours first, with what blocks it) with the branch name to correct — or from a name, with a tick for creating an issue. The config is every section of <code>.sclaude/config.json</code>, explained; a choice made with buttons stays on this machine, outside git. A feature opens its card: the step, ▶️ continue, ⚙️ actions, the dev server — 🌐 in the laptop’s Chrome, 📲 right in the app, ▶️/⏹ start or stop — and 💻 code-server on its worktree. Each feature has a topic of its own: its questions come there, and its card there opens the app on that feature. A review’s start there has its terminal’s keys: ⏭ last pass, ⏹ stop.\nA stopped feature starts when it is opened (about a minute), and one nobody has opened for half an hour stops.\n🌐 <b>Chrome</b> — the laptop’s browser and the list of every feature. 💻 <b>Code-server</b> — VS Code in the browser; 📲 opens it in the app.\n\n<b>Working from a terminal</b>\nWith Tailscale on the phone: <b>Termius</b> — host <code>&lt;name&gt;.ts.net</code>, port 22, key auth. This is where <code>sclaude</code> and <code>claude</code> run. While you are connected the laptop stays awake.\n\n<b>Language</b>\nThe bot speaks your Telegram client’s language; ⚙️ Settings → 🌍 Language pins another until you switch back to “Follow Telegram”.'),
    'arch': (
        '<b>🏗 Как это устроено</b>\n\nСчитают в WSL, исполняют в Windows.\n\n<b>1. Детектор</b> (<code>bin/keepawake</code>, systemd-таймер, раз в минуту)\nИщет держателей — тех, из-за кого нельзя усыплять. Записывает результат в файл состояния.\n\n<b>2. Файл состояния</b>\n<code>C:\\Users\\&lt;вы&gt;\\.keepawake\\state.json</code>\nЛежит на диске Windows, потому что его читает PowerShell — и читает тогда, когда WSL может быть уже остановлена. Обратный путь по <code>\\\\wsl$</code> ломается ровно в этот момент.\nВремя в нём — только целые секунды epoch UTC: три рантайма (bash, python, powershell) дают одно число, и переход на летнее время ничего не сдвигает.\n\n<b>3. Windows-сторона</b> (<code>KeepAwake.ps1</code>, автозагрузка)\nРаз в 30 секунд читает файл и держит систему через <code>SetThreadExecutionState</code>. Любой сбой чтения означает «отпустить»: не уснуть — это севший аккумулятор, уснуть рано — нажать кнопку.\n\n<b>4. Бот</b> (<code>keepawake/telegramd.py</code>, systemd)\nШлёт предупреждение за 30 минут и принимает нажатия. Он же спрашивает раз в час, если жёсткие держат, а работы не видно.\n\nНичего не слушает наружу: бот сам ходит к Telegram, портов не открывает.',
        '<b>🏗 How it works</b>\n\nWSL decides, Windows enforces.\n\n<b>1. Detector</b> (<code>bin/keepawake</code>, systemd timer, every minute)\nLooks for holders — whatever makes sleeping wrong right now. Writes the verdict to the state file.\n\n<b>2. State file</b>\n<code>C:\\Users\\&lt;you&gt;\\.keepawake\\state.json</code>\nIt lives on the Windows drive because PowerShell reads it — and reads it exactly when WSL may already be stopped. The other way round, over <code>\\\\wsl$</code>, breaks at that very moment.\nTime in it is plain UTC epoch seconds: bash, python and powershell all produce the same integer, and daylight saving shifts nothing.\n\n<b>3. Windows side</b> (<code>KeepAwake.ps1</code>, startup folder)\nReads the file every 30 s and holds the system with <code>SetThreadExecutionState</code>. Any read failure means "release": not sleeping costs a flat battery, sleeping early costs one button press.\n\n<b>4. Bot</b> (<code>keepawake/telegramd.py</code>, systemd)\nSends the 30-minute warning and takes the button presses. It also asks hourly when hard holders are up but no work is visible.\n\nNothing listens from outside: the bot dials Telegram itself and opens no ports.'),
    'holders': (
        '<b>🔒 Держатели</b>\n\n<b>Жёсткие</b> — удалённая работа: кто-то дотянулся до машины с телефона. Сон не наступает вовсе, таймер не идёт, вопросов не задаётся.\n• SSH-сессия (Termius)\n• открытая вкладка code-server\n• трафик в tailnet\n\n<b>Мягкие</b> — работа идёт, но человека рядом может не быть. Дают час с последней активности, потом бот спрашивает.\n• занятый <code>claude</code>\n• работающий шаг <code>sclaude</code>\n• открытый VS Code (Remote-WSL)\n• запущенный dev-сервер\n• служба code-server\n\n<b>Никого</b> — Windows засыпает по своим настройкам (у вас 15 минут простоя).\n\nТонкости, которые стоило выяснить опытом:\n\n<b>Час не накапливается.</b> Пока жив хоть один держатель, срок — всегда «час от текущего момента». Иначе три коротких подключения оставили бы ноутбук бодрым на три часа после того, как все закрылись.\n\n<b>Занятость claude меряется по CPU.</b> Открытая сессия, ждущая ввода, не работа: однажды она продержала ноутбук всю ночь.\n\n<b>Работа за самим ноутбуком жёстким держателем не считается.</b> Все три жёстких — способы дотянуться до машины удалённо; клавиатуру и экран Windows из WSL не видно. Когда вы за ноутбуком, держит обычно <code>claude</code> — мягким, то есть с часовым сроком и вопросом в конце.\n\n<b>Tailscale считается по Active, а не Online.</b> Телефон присутствует в сети круглые сутки; удержание по присутствию не дало бы уснуть никогда.\n\n<b>Сессия code-server ≠ служба.</b> Вкладку определяем по файлу heartbeat, который сервер трогает раз в минуту. Считать процессы нельзя: они доживают три часа после закрытия вкладки.',
        '<b>🔒 Holders</b>\n\n<b>Hard</b> — remote work: someone has reached the machine from a phone. No sleep at all, no timer, no questions.\n• an SSH session (Termius)\n• an open code-server tab\n• tailnet traffic\n\n<b>Soft</b> — work is running, but nobody may be around. They buy an hour from the last activity, then the bot asks.\n• a busy <code>claude</code>\n• a running <code>sclaude</code> step\n• VS Code open over Remote-WSL\n• a running dev server\n• the code-server service\n\n<b>Nobody</b> — Windows sleeps by its own settings (15 minutes idle here).\n\nDetails worth learning the hard way:\n\n<b>The hour does not accumulate.</b> While any holder lives, the deadline is always "an hour from now". Otherwise three brief connections would keep the laptop awake for three hours after all of them closed.\n\n<b>A busy claude is measured by CPU.</b> A session waiting for input is not work: one once kept the laptop awake all night.\n\n<b>Working at the laptop itself is not a hard holder.</b> All three hard holders are ways of reaching the machine remotely; the Windows keyboard and screen are invisible from WSL. When you are at the laptop, what usually holds is <code>claude</code> — softly, with the hour and the question at the end.\n\n<b>Tailscale counts Active, not Online.</b> A phone is present on the network around the clock; holding on presence would mean never sleeping.\n\n<b>A code-server session is not the service.</b> The tab is detected through the heartbeat file the server touches every minute. Counting processes fails: they outlive a closed tab by three hours.'),
    'install': (
        '<b>💾 Установка с нуля</b>\n\n<b>0. Tailscale — первым делом</b>\nСтавится <b>внутри WSL</b>, не в Windows: адрес нужен Ubuntu, где живут sshd и code-server.\n<code>curl -fsSL https://tailscale.com/install.sh | sh\nsudo tailscale up</code>\nЗатем то же приложение на телефон, вход в тот же аккаунт; <code>tailscale status</code> покажет обе ноды.\nПобочный эффект: сама Windows в сеть не входит, поэтому с ноутбука адрес <code>100.x</code> недоступен — для него в меню есть отдельные локальные ссылки.\n\n<b>1. Репозиторий и симлинки</b>\n<code>git clone git@github.com:personalautomation/SClaude.git ~/sclaude\ncd ~/sclaude &amp;&amp; ./install.sh</code>\nИдемпотентно, запускать сколько угодно раз. Разложит симлинки, скопирует PowerShell-скрипт на диск Windows, положит VBS в автозагрузку, включит таймер.\n\n<b>2. Требует sudo — руками</b>\n<code>sudo apt-get install -y openssh-server\nsudo loginctl enable-linger $USER</code>\nВторое обязательно: без него <code>systemctl --user</code> умирает вместе с последним терминалом, то есть бот замолкает, как только вы закроете окно WSL.\n\n<b>3. SSH только в tailnet</b>\n<code>/etc/ssh/sshd_config.d/10-keepawake.conf</code>:\n<code>ListenAddress &lt;ваш tailscale IP&gt;\nPasswordAuthentication no\nPubkeyAuthentication yes\nPermitRootLogin no</code>\nЗатем <code>sudo systemctl enable --now ssh</code>.\nКлюч генерируйте на телефоне (Termius → Keychain → Generate, ED25519), публичную часть — в <code>~/.ssh/authorized_keys</code> (600, каталог 700); приватная пусть остаётся на телефоне.\nВ Termius заводите хост: MagicDNS-имя <code>&lt;нода&gt;.tsXXXX.ts.net</code> (переживёт смену адреса), порт 22, ваш пользователь, пароль пустой.\n\n<b>4. Telegram</b>\nБот у @BotFather, свой chat_id через <code>getUpdates</code>, оба значения в <code>~/.config/keepawake/env</code> (chmod 600), затем\n<code>systemctl --user enable --now keepawake-telegram</code>\n\n<b>5. code-server</b>\n<code>curl -fsSL https://code-server.dev/install.sh | sh -s -- --method standalone --prefix ~/.local</code>\nКонфиг <code>~/.config/code-server/config.yaml</code>: bind-addr на tailscale-адрес, пароль, <code>idle-timeout-seconds: 3540</code>.\nАвтозапуск не нужен — поднимается кнопкой.\n\nПроброс портов и правила файрвола не нужны: Tailscale стоит внутри WSL, трафик приходит прямо на её интерфейс.\n\n<b>Без Windows</b>\nНа обычном Linux <code>install.sh</code> ставит <code>keepawake-linux</code> вместо PowerShell-части. Без polkit-правила из docs/tools.md держится только простой: закрытая крышка всё равно усыпит машину.\n\n<b>Бот у каждого свой</b>\nОдин токен читает одна машина, общий бот на команду невозможен.',
        '<b>💾 Install from scratch</b>\n\n<b>0. Tailscale first</b>\nIt goes <b>inside WSL</b>, not on Windows: the address is needed by Ubuntu, where sshd and code-server live.\n<code>curl -fsSL https://tailscale.com/install.sh | sh\nsudo tailscale up</code>\nThen the same app on the phone, same account; <code>tailscale status</code> should list both nodes.\nSide effect: Windows itself is not on the network, so the <code>100.x</code> address is unreachable from the laptop — that is what the separate local links in the menu are for.\n\n<b>1. Repository and symlinks</b>\n<code>git clone git@github.com:personalautomation/SClaude.git ~/sclaude\ncd ~/sclaude &amp;&amp; ./install.sh</code>\nIdempotent, run it as often as you like. It places symlinks, copies the PowerShell script to the Windows drive, drops the VBS into Startup and enables the timer.\n\n<b>2. Needs sudo — by hand</b>\n<code>sudo apt-get install -y openssh-server\nsudo loginctl enable-linger $USER</code>\nThe second one is mandatory: without it <code>systemctl --user</code> dies with your last terminal, so the bot goes silent the moment you close the WSL window.\n\n<b>3. SSH on the tailnet only</b>\n<code>/etc/ssh/sshd_config.d/10-keepawake.conf</code>:\n<code>ListenAddress &lt;your tailscale IP&gt;\nPasswordAuthentication no\nPubkeyAuthentication yes\nPermitRootLogin no</code>\nThen <code>sudo systemctl enable --now ssh</code>.\nGenerate the key on the phone (Termius → Keychain → Generate, ED25519); the public half goes to <code>~/.ssh/authorized_keys</code> (600, directory 700), the private half stays there.\nIn Termius add a host: the MagicDNS name <code>&lt;node&gt;.tsXXXX.ts.net</code> (it survives an address change), port 22, your username, empty password.\n\n<b>4. Telegram</b>\nA bot from @BotFather, your chat_id via <code>getUpdates</code>, both into <code>~/.config/keepawake/env</code> (chmod 600), then\n<code>systemctl --user enable --now keepawake-telegram</code>\n\n<b>5. code-server</b>\n<code>curl -fsSL https://code-server.dev/install.sh | sh -s -- --method standalone --prefix ~/.local</code>\nConfig <code>~/.config/code-server/config.yaml</code>: bind-addr on the tailscale address, a password, <code>idle-timeout-seconds: 3540</code>.\nNo autostart — a button brings it up.\n\nNo port forwarding or firewall rules: Tailscale runs inside WSL, so traffic lands on its interface directly.\n\n<b>Without Windows</b>\nOn plain Linux <code>install.sh</code> installs <code>keepawake-linux</code> instead of the PowerShell side. Without the polkit rule from docs/tools.md it holds idle only: a closed lid still puts the machine to sleep.\n\n<b>Everyone has their own bot</b>\nOne token is read by one machine, so a shared team bot is not possible.'),
    'files': (
        '<b>📂 Файлы и службы</b>\n\n<b>В WSL</b>\n<code>bin/keepawake</code> — детектор, <code>status</code>, ручное продление\n<code>bin/code-server-start</code> — открывает выбранный репозиторий\n<code>bin/code-server-proxy</code> — проброс localhost, адрес из конфига\n<code>keepawake/state.py</code> — состояние под flock, атомарная запись\n<code>keepawake/telegramd.py</code> — бот\n<code>keepawake/i18n.py</code> — строки на двух языках\n\n<b>Службы (systemctl --user)</b>\n<code>keepawake.timer</code> — минутный опрос\n<code>keepawake-telegram</code> — бот, Restart=always\n<code>keepawake-windows</code> — держит KeepAwake.ps1 живым\n<code>code-server-local.socket</code> — порт для браузера Windows\n<code>code-server</code> — по требованию, без автозапуска\n\n<b>На стороне Windows</b>\n<code>%USERPROFILE%\\.keepawake\\KeepAwake.ps1</code> — удержание\n<code>...\\KeepAwake.vbs</code> — скрытый запуск (запасной способ, руками)\n<code>...\\state.json</code> — состояние\n<code>...\\keepawake-ps.log</code> — журнал удержаний\n\nЗапускает и гасит его systemd в WSL (<code>keepawake-windows</code>), а не автозагрузка Windows: пока дистрибутив не запущен, держать некого, и висящий там процесс не нужен.\nЗадача Планировщика не годится вовсе: <code>schtasks</code> отказывает на триггере входа без прав администратора, а PowerShell из WSL непривилегирован.\n\n<b>Секреты</b>\n<code>~/.config/keepawake/env</code> — токен и chat_id, chmod 600\n<code>~/.config/code-server/config.yaml</code> — пароль, chmod 600\nВ репозитории их нет и быть не должно.',
        '<b>📂 Files and services</b>\n\n<b>In WSL</b>\n<code>bin/keepawake</code> — detector, <code>status</code>, manual extend\n<code>bin/code-server-start</code> — opens the chosen repository\n<code>bin/code-server-proxy</code> — localhost proxy, address from config\n<code>keepawake/state.py</code> — state under flock, atomic writes\n<code>keepawake/telegramd.py</code> — the bot\n<code>keepawake/i18n.py</code> — strings in two languages\n\n<b>Services (systemctl --user)</b>\n<code>keepawake.timer</code> — the one-minute poll\n<code>keepawake-telegram</code> — the bot, Restart=always\n<code>keepawake-windows</code> — keeps KeepAwake.ps1 alive\n<code>code-server-local.socket</code> — the port for the Windows browser\n<code>code-server</code> — on demand, no autostart\n\n<b>On the Windows side</b>\n<code>%USERPROFILE%\\.keepawake\\KeepAwake.ps1</code> — the hold\n<code>...\\KeepAwake.vbs</code> — hidden launch (a manual fallback)\n<code>...\\state.json</code> — the state\n<code>...\\keepawake-ps.log</code> — the hold journal\n\nsystemd in WSL starts and stops it (<code>keepawake-windows</code>), not the Windows Startup folder: while the distro is down there is nobody to hold for, and a process lingering there is pointless.\nA Scheduled Task is no use either: <code>schtasks</code> refuses a logon trigger without administrator rights, and PowerShell launched from WSL is unprivileged.\n\n<b>Secrets</b>\n<code>~/.config/keepawake/env</code> — token and chat_id, chmod 600\n<code>~/.config/code-server/config.yaml</code> — password, chmod 600\nNeither belongs in the repository.'),
    'trouble': (
        '<b>🔧 Если что-то не так</b>\n\n<b>Первым делом</b>\n<code>keepawake status</code> — вся картина сразу: два раздела — «HOLD» (до какого времени держим, кто держит, адреса для входа) и «HEALTH» со светофором (система, удалённый доступ, версия инструментов). Второй разворачивается в подробности, только когда сломался.\n\n<b>Ноутбук не засыпает</b>\nВ разделе «HOLD» перечислены держатели: чаще всего это забытая сессия. Кнопка «Пусть спит» снимает удержание досрочно.\n\n<b>Засыпает во время работы</b>\nРаздел «HEALTH» краснеет 🔴, если Windows-сторона не держит. Если «не запущен» — запустите вручную:\n<code>%USERPROFILE%\\.keepawake\\KeepAwake.vbs</code>\n\n<b>Бот молчит</b>\n<code>journalctl --user -u keepawake-telegram -n 30</code>\nHTTP 409 означает второй экземпляр на том же токене, 401 — неверный токен.\n\n<b>Кнопки отвечают «not found»</b>\nУ сервиса нет ваших путей в PATH. Это повторялось шесть раз: cmd.exe, ~/.local/bin, tasklist.exe, npm из nvm. Проверяйте команду в окружении сервиса:\n<code>systemd-run --user --wait --pipe &lt;команда&gt;</code>\n\n<b>Windows-сторона не запускается</b>\nPowerShell 5.1 читает UTF-8 без BOM как ANSI, и кириллица в комментариях ломает разбор. install.sh копирует файл с BOM — не заменяйте на обычный cp.\n\n<b>Проверить всё разом</b>\n<code>python3 ~/sclaude/tests/keepawake.py</code>',
        '<b>🔧 Troubleshooting</b>\n\n<b>Start here</b>\n<code>keepawake status</code> — the whole picture in two sections: "HOLD" (until when we hold, who holds, the addresses to connect to) and "HEALTH" with a traffic light (the machinery, remote access, the tools version). The second expands into details only when something is broken.\n\n<b>The laptop will not sleep</b>\nThe "HOLD" section lists the holders: usually a forgotten session. The "Let it sleep" button drops the hold early.\n\n<b>It sleeps mid-work</b>\nThe "HEALTH" section turns red 🔴 when the Windows side is not holding. If it says not running, start it by hand:\n<code>%USERPROFILE%\\.keepawake\\KeepAwake.vbs</code>\n\n<b>The bot is silent</b>\n<code>journalctl --user -u keepawake-telegram -n 30</code>\nHTTP 409 means a second instance on the same token, 401 a wrong token.\n\n<b>Buttons answer "not found"</b>\nThe service has none of your paths in PATH. This bit six times: cmd.exe, ~/.local/bin, tasklist.exe, npm from nvm. Test a command in the service environment:\n<code>systemd-run --user --wait --pipe &lt;command&gt;</code>\n\n<b>The Windows side will not start</b>\nPowerShell 5.1 reads UTF-8 without BOM as ANSI, and Cyrillic in comments breaks parsing. install.sh copies the file with a BOM — do not replace that with a plain cp.\n\n<b>Check everything at once</b>\n<code>python3 ~/sclaude/tests/keepawake.py</code>'),
}


# --- on a Mac -------------------------------------------------------------------
#
# The sections above are written for WSL, where the bot was born: Windows holds
# the machine, systemd runs the services, Tailscale lives inside the
# distribution. On a Mac every one of those is different — launchd's agents, a
# power assertion, Tailscale's own app — so the sections that say how the
# machinery works, how to set it up and how to mend it have a Mac's version,
# which section() gives when the bot runs there. 'usage' and the rest of 'why'
# are the same on both.

def _mac_why(text, ru):
    """'why' with its two WSL remarks put the Mac's way."""
    if ru:
        return (text.replace("ни при перезапуске WSL, ", "ни при перезагрузке, ")
                .replace("Важно: стоит <b>внутри WSL</b>, поэтому адрес принадлежит Ubuntu, а не Windows.",
                         "На Mac это приложение Tailscale: адрес принадлежит самому Mac, и его браузер "
                         "тоже открывает адреса tailnet."))
    return (text.replace("that survives a WSL restart, ", "that survives a reboot, ")
            .replace("Note: it runs <b>inside WSL</b>, so the address belongs to Ubuntu, not Windows.",
                     "On a Mac it is the Tailscale app: the address belongs to the Mac itself, and its own "
                     "browser opens tailnet addresses too."))


MAC_SECTIONS = {
    'why': (_mac_why(SECTIONS['why'][0], True), _mac_why(SECTIONS['why'][1], False)),
    'arch': (
        '<b>🏗 Как это устроено на Mac</b>\n\n'
        'Всё работает агентами launchd в вашей сессии (<code>~/Library/LaunchAgents</code>).\n\n'
        '<b>1. Детектор</b> (<code>bin/keepawake</code>, агент <code>keepawake</code>, раз в минуту)\n'
        'Ищет держателей — тех, из-за кого нельзя усыплять. Записывает результат в файл состояния.\n\n'
        '<b>2. Файл состояния</b>\n<code>~/.local/state/keepawake/state.json</code>\n'
        'Время в нём — только целые секунды epoch UTC: переход на летнее время ничего не сдвигает.\n\n'
        '<b>3. Удержание</b> (<code>keepawake-macos</code>, агент <code>keepawake.hold</code>)\n'
        'Раз в 30 секунд читает файл и, пока он велит держать, держит power assertion: '
        '<code>pmset -g assertions</code> показывает её как «keepawake: work in progress». '
        'Умер процесс — macOS снимает её сама, то есть сбой означает «отпустить». '
        'Закрытую крышку держит только необязательное правило sudoers для '
        '<code>pmset -a disablesleep</code>.\n\n'
        '<b>4. Бот</b> (<code>keepawake/telegramd.py</code>, агент <code>keepawake.telegram</code>)\n'
        'Шлёт предупреждение за 30 минут и принимает нажатия. Он же спрашивает раз в час, '
        'если жёсткие держат, а работы не видно.\n\n'
        'Наружу ничего не слушает: бот сам ходит к Telegram. Единственная дверь — вход с телефона '
        '(агент <code>sclaude.gate</code> за <code>tailscale funnel</code>), и открыта она, '
        'только пока доступ с телефона включён.',
        '<b>🏗 How it works on a Mac</b>\n\n'
        'Everything runs as launchd agents in your login session (<code>~/Library/LaunchAgents</code>).\n\n'
        '<b>1. Detector</b> (<code>bin/keepawake</code>, agent <code>keepawake</code>, every minute)\n'
        'Looks for holders — whatever makes sleeping wrong right now. Writes the verdict to the state file.\n\n'
        '<b>2. State file</b>\n<code>~/.local/state/keepawake/state.json</code>\n'
        'Time in it is plain UTC epoch seconds, so daylight saving shifts nothing.\n\n'
        '<b>3. Holding side</b> (<code>keepawake-macos</code>, agent <code>keepawake.hold</code>)\n'
        'Reads the file every 30 s and, while it says to hold, keeps a power assertion: '
        '<code>pmset -g assertions</code> shows it as "keepawake: work in progress". '
        'macOS drops it when the process dies, so a crash means "release". A closed lid is held only '
        'with the optional sudoers rule for <code>pmset -a disablesleep</code>.\n\n'
        '<b>4. Bot</b> (<code>keepawake/telegramd.py</code>, agent <code>keepawake.telegram</code>)\n'
        'Sends the 30-minute warning and takes the button presses. It also asks hourly when hard '
        'holders are up but no work is visible.\n\n'
        'Nothing listens from outside: the bot dials Telegram itself. The one door is the phone\'s '
        'entry (agent <code>sclaude.gate</code> behind <code>tailscale funnel</code>), open only '
        'while phone access is on.'),
    'holders': (
        '<b>🔒 Держатели</b>\n\n'
        '<b>Жёсткие</b> — удалённая работа: кто-то дотянулся до Mac с телефона. Сон не наступает вовсе, '
        'таймер не идёт, вопросов не задаётся.\n'
        '• SSH-сессия (Termius; нужен Remote Login)\n• открытая вкладка code-server\n• трафик в tailnet\n\n'
        '<b>Мягкие</b> — работа идёт, но человека рядом может не быть. Дают час с последней активности, '
        'потом бот спрашивает.\n'
        '• занятый <code>claude</code>\n• работающий шаг <code>sclaude</code>\n'
        '• VS Code, подключённый по Remote-SSH\n• запущенный dev-сервер\n• служба code-server\n\n'
        '<b>Никого</b> — Mac засыпает по своим настройкам (Системные настройки → Аккумулятор).\n\n'
        'Тонкости:\n\n'
        '<b>Час не накапливается.</b> Пока жив хоть один держатель, срок — всегда «час от текущего '
        'момента».\n\n'
        '<b>Занятость claude меряется по CPU.</b> Открытая сессия, ждущая ввода, не работа.\n\n'
        '<b>Клавиатура и мышь самого Mac — признак присутствия.</b> Пока вы их трогаете, мягкие держат '
        'без вопроса: работа в редакторе или браузере не выглядит как «час без ввода». Жёстким '
        'держателем это не становится: отошли от Mac — час истекает как обычно.\n\n'
        '<b>Tailscale считается по Active, а не Online.</b> Телефон присутствует в сети круглые сутки; '
        'удержание по присутствию не дало бы уснуть никогда.\n\n'
        '<b>Сессия code-server ≠ служба.</b> Вкладку определяем по файлу heartbeat, который сервер '
        'трогает раз в минуту.',
        '<b>🔒 Holders</b>\n\n'
        '<b>Hard</b> — remote work: someone has reached the Mac from a phone. No sleep at all, no timer, '
        'no questions.\n'
        '• an SSH session (Termius; needs Remote Login)\n• an open code-server tab\n• tailnet traffic\n\n'
        '<b>Soft</b> — work is running, but nobody may be around. They buy an hour from the last '
        'activity, then the bot asks.\n'
        '• a busy <code>claude</code>\n• a running <code>sclaude</code> step\n'
        '• VS Code connected over Remote-SSH\n• a running dev server\n• the code-server service\n\n'
        '<b>Nobody</b> — the Mac sleeps by its own settings (System Settings → Battery).\n\n'
        'Details:\n\n'
        '<b>The hour does not accumulate.</b> While any holder lives, the deadline is always "an hour '
        'from now".\n\n'
        '<b>A busy claude is measured by CPU.</b> A session waiting for input is not work.\n\n'
        '<b>The Mac\'s own keyboard and mouse count as presence.</b> While you use them, soft holders '
        'keep holding without the question: work in an editor or a browser does not look like "an hour '
        'without input". It is not a hard holder: walk away and the hour runs out as usual.\n\n'
        '<b>Tailscale counts Active, not Online.</b> A phone is present on the network around the '
        'clock; holding on presence would mean never sleeping.\n\n'
        '<b>A code-server session is not the service.</b> The tab is detected through the heartbeat '
        'file the server touches every minute.'),
    'install': (
        '<b>💾 Установка на Mac</b>\n\n'
        '<b>0. Tailscale</b>\nПриложение Tailscale на Mac и на телефон, вход в один аккаунт. '
        'Боту нужна команда <code>tailscale</code>: приложение ставит её из своих настроек '
        '(или <code>brew install tailscale</code>).\n\n'
        '<b>1. Репозиторий</b>\n'
        '<code>git clone git@github.com:personalautomation/SClaude.git ~/sclaude\n'
        'cd ~/sclaude &amp;&amp; ./install.sh --extras</code>\n'
        'Предложит поставить из Homebrew bash и GNU-утилиты, запишет и загрузит агенты launchd. '
        'Запускать можно сколько угодно раз.\n\n'
        '<b>2. SSH для Termius</b>\nСистемные настройки → Основные → Общий доступ → Удалённый вход. '
        'Ключ генерируйте на телефоне (Termius → Keychain → Generate, ED25519), публичную часть — '
        'в <code>~/.ssh/authorized_keys</code>. Хост — MagicDNS-имя <code>&lt;нода&gt;.tsXXXX.ts.net</code>.\n\n'
        '<b>3. Telegram</b>\nБот у @BotFather, свой chat_id через <code>getUpdates</code>, оба значения '
        'в <code>~/.config/keepawake/env</code> (chmod 600), затем снова <code>./install.sh</code>: '
        'агент бота пишется, только когда на месте и токен, и chat_id. Токен остаётся в файле — бот читает его сам.\n\n'
        '<b>4. code-server</b>\n<code>brew install code-server</code>\n'
        'Конфиг <code>~/.config/code-server/config.yaml</code>: bind-addr на tailscale-адрес, пароль, '
        '<code>idle-timeout-seconds: 3540</code>. Автозапуска нет — поднимается кнопкой.\n\n'
        '<b>5. Крышка</b>\nЗакрытую крышку держит только правило sudoers для <code>pmset</code>: '
        '<code>./install.sh --lid</code>.\n\n'
        '<b>Бот у каждого свой</b>\nОдин токен читает одна машина, общий бот на команду невозможен.',
        '<b>💾 Install on a Mac</b>\n\n'
        '<b>0. Tailscale</b>\nThe Tailscale app on the Mac and on the phone, same account. The bot needs '
        'the <code>tailscale</code> command: the app installs it from its settings (or '
        '<code>brew install tailscale</code>).\n\n'
        '<b>1. Repository</b>\n'
        '<code>git clone git@github.com:personalautomation/SClaude.git ~/sclaude\n'
        'cd ~/sclaude &amp;&amp; ./install.sh --extras</code>\n'
        'It offers Homebrew\'s bash and GNU tools, then writes and loads the launchd agents. Run it as '
        'often as you like.\n\n'
        '<b>2. SSH for Termius</b>\nSystem Settings → General → Sharing → Remote Login. Generate the key '
        'on the phone (Termius → Keychain → Generate, ED25519); the public half goes to '
        '<code>~/.ssh/authorized_keys</code>. The host is the MagicDNS name '
        '<code>&lt;node&gt;.tsXXXX.ts.net</code>.\n\n'
        '<b>3. Telegram</b>\nA bot from @BotFather, your chat_id via <code>getUpdates</code>, both into '
        '<code>~/.config/keepawake/env</code> (chmod 600), then <code>./install.sh</code> again: the '
        'bot\'s agent is written only once both the token and the chat_id are there. The token stays in the file — the bot '
        'reads it itself.\n\n'
        '<b>4. code-server</b>\n<code>brew install code-server</code>\n'
        'Config <code>~/.config/code-server/config.yaml</code>: bind-addr on the tailscale address, a '
        'password, <code>idle-timeout-seconds: 3540</code>. No autostart — a button brings it up.\n\n'
        '<b>5. The lid</b>\nA closed lid is held only with a sudoers rule for <code>pmset</code>: '
        '<code>./install.sh --lid</code>.\n\n'
        '<b>Everyone has their own bot</b>\nOne token is read by one machine, so a shared team bot is '
        'not possible.'),
    'files': (
        '<b>📂 Файлы и службы на Mac</b>\n\n'
        '<b>Код</b>\n'
        '<code>bin/keepawake</code> — детектор, <code>status</code>, ручное продление\n'
        '<code>bin/keepawake-macos</code> — power assertion и крышка\n'
        '<code>bin/code-server-start</code> — открывает выбранный репозиторий\n'
        '<code>keepawake/telegramd.py</code> — бот\n'
        '<code>keepawake/units.py</code> — чем кнопки запускают и останавливают службы\n\n'
        '<b>Агенты launchd</b> (<code>~/Library/LaunchAgents</code>)\n'
        '<code>keepawake</code> — минутный опрос\n'
        '<code>keepawake.hold</code> — удержание\n'
        '<code>keepawake.telegram</code> — бот, перезапускается всегда\n'
        '<code>keepawake.code-server</code> — по кнопке, без автозапуска\n'
        '<code>sclaude.gate</code> — вход с телефона, launchd поднимает его по первому подключению\n\n'
        '<b>Журналы</b>\n<code>~/Library/Logs/sclaude/</code> — вывод агентов (бот — <code>telegram.log</code>)\n'
        '<code>~/.local/state/keepawake/hold.log</code> — журнал удержаний\n\n'
        '<b>Секреты</b>\n'
        '<code>~/.config/keepawake/env</code> — токен и chat_id, chmod 600\n'
        '<code>~/.config/code-server/config.yaml</code> — пароль, chmod 600\n'
        'В репозитории и в plist их нет и быть не должно.',
        '<b>📂 Files and services on a Mac</b>\n\n'
        '<b>Code</b>\n'
        '<code>bin/keepawake</code> — detector, <code>status</code>, manual extend\n'
        '<code>bin/keepawake-macos</code> — the power assertion and the lid\n'
        '<code>bin/code-server-start</code> — opens the chosen repository\n'
        '<code>keepawake/telegramd.py</code> — the bot\n'
        '<code>keepawake/units.py</code> — how buttons start and stop services\n\n'
        '<b>launchd agents</b> (<code>~/Library/LaunchAgents</code>)\n'
        '<code>keepawake</code> — the one-minute poll\n'
        '<code>keepawake.hold</code> — the hold\n'
        '<code>keepawake.telegram</code> — the bot, always restarted\n'
        '<code>keepawake.code-server</code> — on a button, no autostart\n'
        '<code>sclaude.gate</code> — the phone\'s entry, started by launchd on the first connection\n\n'
        '<b>Logs</b>\n<code>~/Library/Logs/sclaude/</code> — the agents\' output (the bot: '
        '<code>telegram.log</code>)\n'
        '<code>~/.local/state/keepawake/hold.log</code> — the hold journal\n\n'
        '<b>Secrets</b>\n'
        '<code>~/.config/keepawake/env</code> — token and chat_id, chmod 600\n'
        '<code>~/.config/code-server/config.yaml</code> — password, chmod 600\n'
        'Neither belongs in the repository or a plist.'),
    'trouble': (
        '<b>🔧 Если что-то не так</b>\n\n'
        '<b>Первым делом</b>\n<code>keepawake status</code> — вся картина: разделы «HOLD» и «HEALTH».\n'
        '<code>sclaude doctor</code> — какие агенты не загружены и чем это исправить.\n\n'
        '<b>Mac не засыпает</b>\nВ разделе «HOLD» перечислены держатели: чаще всего это забытая сессия. '
        'Кнопка «Пусть спит» снимает удержание досрочно. Кто ещё держит Mac, кроме нас: '
        '<code>pmset -g assertions</code>.\n\n'
        '<b>Засыпает во время работы</b>\n«HEALTH» краснеет 🔴, если удержание не работает. '
        'Закрытая крышка без правила sudoers усыпит Mac всё равно: <code>./install.sh --lid</code>.\n\n'
        '<b>Бот молчит</b>\n<code>tail -n 50 ~/Library/Logs/sclaude/telegram.log</code>\n'
        '<code>launchctl print gui/$(id -u)/keepawake.telegram</code>\n'
        'HTTP 409 означает второй экземпляр на том же токене, 401 — неверный токен. Агента нет вовсе — '
        'нет токена в <code>~/.config/keepawake/env</code>; впишите его и запустите '
        '<code>./install.sh</code>.\n\n'
        '<b>Кнопки отвечают «not found»</b>\nУ агента PATH той оболочки, из которой запускали '
        '<code>install.sh</code>. Нужная команда появилась позже — запустите его снова из оболочки, где '
        'она находится.\n\n'
        '<b>Нет ссылок на телефон, не включается доступ с телефона</b>\nНет команды '
        '<code>tailscale</code> в PATH: поставьте её из настроек приложения Tailscale.\n\n'
        '<b>Проверить всё разом</b>\n<code>~/sclaude/tests/run keepawake</code>',
        '<b>🔧 Troubleshooting</b>\n\n'
        '<b>Start here</b>\n<code>keepawake status</code> — the whole picture: "HOLD" and "HEALTH".\n'
        '<code>sclaude doctor</code> — which agents are not loaded, and the fix for each.\n\n'
        '<b>The Mac will not sleep</b>\nThe "HOLD" section lists the holders: usually a forgotten '
        'session. The "Let it sleep" button drops the hold early. Who else holds the Mac: '
        '<code>pmset -g assertions</code>.\n\n'
        '<b>It sleeps mid-work</b>\n"HEALTH" turns red 🔴 when the hold is not working. A closed lid '
        'still puts the Mac to sleep without the sudoers rule: <code>./install.sh --lid</code>.\n\n'
        '<b>The bot is silent</b>\n<code>tail -n 50 ~/Library/Logs/sclaude/telegram.log</code>\n'
        '<code>launchctl print gui/$(id -u)/keepawake.telegram</code>\n'
        'HTTP 409 means a second instance on the same token, 401 a wrong token. No agent at all means no '
        'token in <code>~/.config/keepawake/env</code>; put it there and run <code>./install.sh</code>.\n\n'
        '<b>Buttons answer "not found"</b>\nThe agents have the PATH of the shell '
        '<code>install.sh</code> ran from. A command that arrived later is not on it: run '
        '<code>install.sh</code> again from a shell that finds it.\n\n'
        '<b>No phone links, phone access will not turn on</b>\nNo <code>tailscale</code> command on '
        'PATH: install it from the Tailscale app\'s settings.\n\n'
        '<b>Check everything at once</b>\n<code>~/sclaude/tests/run keepawake</code>'),
}


def section(key, lang):
    pair = SECTIONS.get(key)
    if not pair:
        return ""
    from keepawake import units
    if units.on_macos():
        pair = MAC_SECTIONS.get(key, pair)
    return pair[0] if lang == "ru" else pair[1]
