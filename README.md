Телеграм бот, который уведомляет мейнтейнера ALT Linux об устаревших пакетах. \
Для получения информации о пакетах используется API https://rdb.altlinux.org.

### Установка и настройка

```bash
# apt-get install python3-module-httpx \
                python3-module-telebot \
                python3-module-toml \
                python3-module-schedule \
                python3-module-loguru
# make install
$ cp packages_bot.toml.sample ~/.packages_bot.toml && vim ~/.packages_bot.toml
$ systemctl enable --now --user packages_bot.service
$ systemctl status --user packages_bot.service
```
