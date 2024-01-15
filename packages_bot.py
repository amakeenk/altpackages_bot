#!/usr/bin/python3

import httpx
import json
import telebot
import toml
from loguru import logger
from pathlib import Path

try:
    CONFIG = toml.load(f"{str(Path.home())}/.packages_bot.toml")
    telegram_bot_token = CONFIG["telegram_bot_token"]
    telegram_user_id = CONFIG["telegram_user_id"]
    maintainer_nickname = CONFIG["maintainer_nickname"]
    ignore_packages = CONFIG["ignore_packages"].split(" ")
except FileNotFoundError:
    logger.error(f"Config file not found.")
    exit()
except KeyError as missing_key:
    logger.error(f"Config file is icorrect: {missing_key} not found.")
    exit()


RDB_API_URL = "https://rdb.altlinux.org/api"
QUERY_ACL_NONE = f"{RDB_API_URL}/site/watch_by_maintainer?maintainer_nickname={maintainer_nickname}&by_acl=none"
QUERY_ACL_BY_NICK_LEADER = f"{RDB_API_URL}/site/watch_by_maintainer?maintainer_nickname={maintainer_nickname}&by_acl=by_nick_leader"


def run_query_to_rdb(query):
    try:
        response = httpx.get(url=query, timeout=60)
        if response.status_code == 200:
            return [True, json.loads(response.text)]
        elif response.status_code == 404:
            if "No data found in database" in response.text:
                logger.warning(f"No data found in database")
                return [True, None]
            else:
                logger.error(
                    f"Connection to rdb with query {query} failed: {response.status_code} {response.text}"
                )
                return [False, response.text]
        else:
            logger.error(
                f"Connection to rdb with query {query} failed: {response.status_code} {response.text}"
            )
            return [False, response.text]
    except Exception as error:
        logger.exception(f"Some error occured while run rdb query {query}: {error}")
        return [False, error]


def get_packages_list_from_response(response_body):
    packages_list = []
    for _ in response_body:
        if _["pkg_name"] in ignore_packages:
            continue
        packages_list.append(
            {
                "package_name": _["pkg_name"],
                "new_version": _["new_version"],
                "old_version": _["old_version"],
            }
        )
    return packages_list


def main():
    bot = telebot.TeleBot(telegram_bot_token)
    acl_none_list_response = run_query_to_rdb(QUERY_ACL_NONE)
    acl_by_nick_leader_list_response = run_query_to_rdb(QUERY_ACL_BY_NICK_LEADER)
    if acl_none_list_response[0]:
        acl_none_list = get_packages_list_from_response(
            acl_none_list_response[1]["packages"]
        )
    if acl_by_nick_leader_list_response[0]:
        acl_by_nick_leader_list = get_packages_list_from_response(
            acl_by_nick_leader_list_response[1]["packages"]
        )
    all_packages = list(
        map(
            dict,
            set(
                map(lambda _: tuple(_.items()), acl_none_list + acl_by_nick_leader_list)
            ),
        )
    )
    message_to_user = f"Пакеты с устаревшими версиями ({len(all_packages)}):\n"
    for _ in all_packages:
        message_to_user = (
            message_to_user
            + f"""
Пакет: <a href="https://packages.altlinux.org/ru/sisyphus/srpms/{_["package_name"]}">{_["package_name"]}</a>
Версия в репозитории: {_["old_version"]}
Новая версия: {_["new_version"]}
"""
        )
    bot.send_message(
        telegram_user_id,
        message_to_user,
        parse_mode="html",
        disable_web_page_preview=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        logger.exception(f"ERROR: {err}")
        exit()
