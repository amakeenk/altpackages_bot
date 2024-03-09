```bash
$ sudo apt-get install python3-module-httpx \
                       python3-module-telebot \
                       python3-module-toml \
                       python3-module-schedule \
                       python3-module-loguru
$ git clone git@github.com:amakeenk/altpackages_bot.git && cd altpackages_bot
$ sudo make install
$ cp packages_bot.toml.sample ~/.packages_bot.toml && vim ~/.packages_bot.toml
$ systemctl enable --now --user packages_bot.service
$ systemctl status --user packages_bot.service
```
