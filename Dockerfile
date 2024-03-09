FROM registry.altlinux.org/alt/alt:sisyphus

ENV TZ="Europe/Moscow"

MAINTAINER amakeenk

RUN apt-get update
RUN apt-get dist-upgrade -y
RUN apt-get install -y python3-module-httpx \
                       python3-module-telebot \
                       python3-module-toml \
                       python3-module-loguru \
                       python3-module-schedule \
                       tzdata

ADD packages_bot.py /usr/bin/packages_bot.py
ADD packages_bot.toml /root/.packages_bot.toml

ENTRYPOINT ["/usr/bin/packages_bot.py"]
