# ALT Packages Bot

Телеграм бот, который уведомляет мейнтейнера ALT Linux об устаревших пакетах. \
Бот сканирует спеки мейнтейнера из зеркала https://github.com/altlinux/specs \
и сверяет версии пакетов с апстримом (GitHub, GitLab, PyPI, crates.io). \
Отчёт приходит раз в день с diff'ом относительно предыдущего запуска.

Для всех пакетов независимо ищутся максимальная стабильная и предварительная
версия (alpha, beta, rc и т. п.). В отчёте показываются только версии новее ALT:
например, `wiki-js: 2.5.308 → 2.5.309; prerelease: 3.0.0-beta.617`.
Если обновилась только предварительная версия, она помечается `prerelease`.
Предварительная версия показывается только если она новее и версии ALT,
и найденного стабильного релиза. Она считается ниже финального релиза с тем же номером.
Для GitHub/GitLab учитываются теги, для PyPI/crates.io — также списки версий
(отозванные версии из этих списков исключаются).

### Установка и настройка

```bash
# apt-get install python3-module-telebot \
                python3-module-toml \
                python3-module-schedule \
                python3-module-loguru \
                git-core
# make install
# loginctl enable-linger <user>
$ cp packages_bot.toml.sample ~/.packages_bot.toml && vim ~/.packages_bot.toml
$ systemctl enable --now --user packages_bot.service
$ systemctl status --user packages_bot.service
```

### Настройки

- `telegram_bot_token` — токен телеграм бота
- `telegram_user_id` — id пользователя, которому слать отчёты
- `maintainer_nickname` — ник мейнтейнера в ALT Linux
- `time_to_watch` — время ежедневной отправки отчёта (например, `10:00`)
- `ignore_packages` — список игнорируемых пакетов через пробел (имеет приоритет над `extra_packages`)
- `extra_packages` — необязательный список чужих пакетов через пробел, например `"influxdb3 adguardhome"`; используются имена исходных пакетов в репозитории ALT, а не имена бинарных подпакетов. Они добавляются к своим пакетам без дублей; отсутствующие в зеркале пакеты отмечаются предупреждением в журнале
- `github_token` — опциональный токен GitHub API (снимает rate limit)

Клон спеков и состояние между запусками хранятся в `~/.local/share/packages_bot/`.
