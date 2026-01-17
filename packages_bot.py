#!/usr/bin/python3

import httpx
import json
import schedule
import semver
import telebot
import time
import toml
from loguru import logger
from pathlib import Path

try:
    CONFIG = toml.load(f"{str(Path.home())}/.packages_bot.toml")
    telegram_bot_token = CONFIG["telegram_bot_token"]
    telegram_user_id = CONFIG["telegram_user_id"]
    maintainer_nickname = CONFIG["maintainer_nickname"]
    time_to_watch = CONFIG["time_to_watch"]
    ignore_packages = CONFIG["ignore_packages"].split(" ")
except FileNotFoundError:
    logger.error(f"Config file not found.")
    exit()
except KeyError as missing_key:
    logger.error(f"Config file is incorrect: {missing_key} not found.")
    exit()


RDB_API_URL = "https://rdb.altlinux.org/api"
QUERY_ACL_NONE = f"{RDB_API_URL}/site/watch_by_maintainer?maintainer_nickname={maintainer_nickname}&by_acl=none"
QUERY_ACL_BY_NICK_LEADER = f"{RDB_API_URL}/site/watch_by_maintainer?maintainer_nickname={maintainer_nickname}&by_acl=by_nick_leader"

BOT_INSTANCE = telebot.TeleBot(telegram_bot_token)

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


def compare_versions(version1, version2):
    try:
        v1 = normalize_version_for_semver(version1)
        v2 = normalize_version_for_semver(version2)

        if semver.compare(v1, v2) < 0:
            return -1
        elif semver.compare(v1, v2) > 0:
            return 1
        else:
            if version1 < version2:
                return -1
            elif version1 > version2:
                return 1
            else:
                return 0
    except:
        if version1 < version2:
            return -1
        elif version1 > version2:
            return 1
        else:
            return 0

def normalize_version_for_semver(version):
    parts = version.split('.')

    while len(parts) < 3:
        parts.append('0')

    normalized_parts = []
    for part in parts[:3]:
        import re
        normalized_part = re.sub(r'[^\d]', '', part)
        if not normalized_part:
            normalized_part = '0'
        normalized_parts.append(normalized_part)

    return '.'.join(normalized_parts)

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

def filter_latest_versions(packages_list):
    filtered_packages = {}

    for pkg in packages_list:
        package_name = pkg["package_name"]
        new_version = pkg["new_version"]

        if package_name not in filtered_packages:
            filtered_packages[package_name] = pkg
        else:
            saved_new_version = filtered_packages[package_name]["new_version"]
            comparison_result = compare_versions(new_version, saved_new_version)

            if comparison_result > 0:
                filtered_packages[package_name] = pkg

    return list(filtered_packages.values())


def bot():
    acl_none_list_response = run_query_to_rdb(QUERY_ACL_NONE)
    acl_by_nick_leader_list_response = run_query_to_rdb(QUERY_ACL_BY_NICK_LEADER)

    all_packages = []

    if acl_none_list_response[0] and acl_none_list_response[1] is not None:
        acl_none_list = get_packages_list_from_response(
            acl_none_list_response[1]["packages"]
        )
        all_packages.extend(acl_none_list)

    if acl_by_nick_leader_list_response[0] and acl_by_nick_leader_list_response[1] is not None:
        acl_by_nick_leader_list = get_packages_list_from_response(
            acl_by_nick_leader_list_response[1]["packages"]
        )
        all_packages.extend(acl_by_nick_leader_list)

    # Фильтруем пакеты, оставляя только те с самой новой версией для каждого пакета
    all_packages = filter_latest_versions(all_packages)

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
    BOT_INSTANCE.send_message(
        telegram_user_id,
        message_to_user,
        parse_mode="html",
        disable_web_page_preview=True,
    )


def main():
    BOT_INSTANCE.send_message(
        telegram_user_id,
        f"Бот запущен. Оповещения будут приходить каждый день в {time_to_watch}.",
    )
    schedule.every().day.at(time_to_watch).do(bot)
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        logger.exception(f"ERROR: {err}")
        exit()
