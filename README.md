```bash
$ git clone git@github.com:amakeenk/altpackages_bot.git && cd altpackages_bot
$ sudo make install
$ cp packages_bot.toml.sample ~/.packages_bot.toml && vim ~/.packages_bot.toml
$ systemctl start --user packages_bot.service
$ systemctl status --user packages_bot.service
$ systemctl enable --user packages_bot.timer
```
