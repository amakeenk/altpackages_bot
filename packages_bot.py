#!/usr/bin/python3

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import schedule
import telebot
import toml
from loguru import logger
from telebot.types import MessageEntity

try:
    CONFIG = toml.load(f"{str(Path.home())}/.packages_bot.toml")
    telegram_bot_token = CONFIG["telegram_bot_token"]
    telegram_user_id = CONFIG["telegram_user_id"]
    maintainer_nickname = CONFIG["maintainer_nickname"]
    time_to_watch = CONFIG["time_to_watch"]
    ignore_packages = CONFIG["ignore_packages"].split(" ")
    extra_packages = CONFIG.get("extra_packages", "").split()
    github_token = CONFIG.get("github_token", "")
except FileNotFoundError:
    logger.error("Config file not found.")
    exit()
except KeyError as missing_key:
    logger.error(f"Config file is incorrect: {missing_key} not found.")
    exit()

DATA_DIR = Path.home() / ".local/share/packages_bot"
SPECS_DIR = str(DATA_DIR / "specs")
STATE_FILE = str(DATA_DIR / "prev-outdated.json")
SPECS_REMOTE = "https://github.com/altlinux/specs.git"

BOT_INSTANCE = telebot.TeleBot(telegram_bot_token)

# Never let git prompt for credentials interactively — the bot runs headless.
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def run(args, cwd=None):
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, env=GIT_ENV
    )


def update_specs():
    """Update specs repository.

    Robust against mirror history rewrites: fetch + hard reset of the local
    branch to origin. Aborts the run if the snapshot ends up older than
    MAX_SNAPSHOT_AGE_DAYS.
    """
    MAX_SNAPSHOT_AGE_DAYS = 3
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not Path(SPECS_DIR).is_dir():
        r = run(["git", "clone", "--depth", "50", SPECS_REMOTE, SPECS_DIR])
        if r.returncode != 0:
            logger.error(f"git clone failed: {r.stderr.strip()}")
            sys.exit(1)
    else:
        r = run(["git", "fetch", "--depth", "50", "origin", "sisyphus"], cwd=SPECS_DIR)
        if r.returncode != 0:
            logger.error(f"git fetch failed: {r.stderr.strip()}")
            sys.exit(1)
        r = run(["git", "checkout", "-B", "sisyphus", "origin/sisyphus"], cwd=SPECS_DIR)
        if r.returncode != 0:
            logger.error(f"git reset to origin failed: {r.stderr.strip()}")
            sys.exit(1)

    head_ts = run(["git", "log", "-1", "--format=%ct"], cwd=SPECS_DIR).stdout.strip()
    head_date = run(["git", "log", "-1", "--format=%ci"], cwd=SPECS_DIR).stdout.strip()
    logger.info(f"Specs snapshot: {head_date}")
    try:
        age_days = (datetime.now().timestamp() - float(head_ts)) / 86400
        if age_days > MAX_SNAPSHOT_AGE_DAYS:
            logger.error(
                f"Specs snapshot is {age_days:.1f} days old "
                "(mirror likely stalled); refusing to build a stale report"
            )
            sys.exit(1)
    except (TypeError, ValueError):
        pass


def get_maintainer_packages():
    """Get maintainer packages plus explicitly configured source packages."""
    result = run(["grep", "-rl", maintainer_nickname, f"{SPECS_DIR}/"])
    specs = {p.strip() for p in result.stdout.split("\n") if p.strip().endswith(".spec")}
    requested = set(extra_packages) - set(ignore_packages)
    found = set()
    if requested:
        for spec in Path(SPECS_DIR).glob("*/*/*.spec"):
            if spec.parent.name in requested:
                specs.add(str(spec))
                found.add(spec.parent.name)
        for name in sorted(requested - found):
            logger.warning(f"Extra package not found in specs: {name}")
    packages = []
    for spec in sorted(specs):
        try:
            with open(spec, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError as e:
            logger.warning(f"Failed to read spec {spec}: {e}")
            continue

        name_match = re.search(r"^Name:\s*(.+)$", content, re.MULTILINE)
        version_match = re.search(r"^Version:\s*(.+)$", content, re.MULTILINE)
        url_match = re.search(r"^URL:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
        vcs_match = re.search(r"^VCS:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)

        if name_match and version_match:
            name = name_match.group(1).strip()
            version = version_match.group(1).strip()
            url = url_match.group(1).strip() if url_match else ""
            vcs = vcs_match.group(1).strip() if vcs_match else ""

            # Mirror directories are named after source packages; spec filenames
            # and macro-expanded upstream names need not match that identity.
            pkg_name = Path(spec).parent.name

            if pkg_name in ignore_packages:
                continue

            # Skip if name contains macros
            if "%" in name:
                mod_match = re.search(
                    r"%define\s+(?:module_name|pypi_name|modulename|modname)\s+(.+)",
                    content,
                    re.IGNORECASE,
                )
                if mod_match:
                    name = mod_match.group(1).strip()
                else:
                    name = Path(spec).parent.name

            packages.append(
                {
                    "name": name,
                    "pkg_name": pkg_name,
                    "alt_version": version,
                    "url": url,
                    "vcs": vcs,
                    "spec": spec,
                }
            )
    return packages


def fetch_json(url, headers=None):
    """Fetch JSON from URL. Returns parsed JSON, or the error body dict on HTTPError."""
    if not url.startswith(("https://", "http://")):
        logger.warning(f"Refusing to fetch non-http(s) URL: {url}")
        return None
    try:
        req = urllib.request.Request(url, headers=headers or {})  # noqa: S310
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return None
    except Exception:
        return None


def normalize_version(v):
    """Normalize version string for comparison."""
    if not v or v == "%version":
        return None
    v = v.strip().lower()
    v = re.sub(r"^(v|version|release|mdcat-|bats-)", "", v)
    v = re.sub(r"[-_+]?(alt\d+|git\w*|dfsg\d*|ds)$", "", v)
    parts = re.split(r"[.\-_]", v)
    result = []
    for p in parts:
        if p.isdigit():
            result.append(int(p))
        elif p:
            # Handle mixed parts like '0b', '0alpha', '0rc1'
            m = re.match(r"(\d+)([a-z]+)(\d*)", p)
            if m:
                result.append(int(m.group(1)))
                result.append(m.group(2))
                if m.group(3):
                    result.append(int(m.group(3)))
            else:
                result.append(p)
    return result


def version_sort_key(v):
    """Comparable sort key from a version string. None sorts lowest."""
    nv = normalize_version(v)
    if nv is None:
        return (0,)
    key: list = [1]
    for part in nv:
        if isinstance(part, int):
            key.append((1, part, ""))
        else:
            key.append((0, 0, str(part)))
    return tuple(key)


def compare_versions(v1, v2):
    """Simple version comparison. Returns True if v2 > v1."""
    nv1 = normalize_version(v1)
    nv2 = normalize_version(v2)
    if not nv1 or not nv2:
        return False
    try:
        return nv2 > nv1
    except Exception:
        return False


def latest_tag_via_git(host, owner, repo):
    """Get latest tag using git protocol — bypasses API rate limits.

    Prefers stable tags; only falls back to pre-release tags (rc/beta/alpha...)
    if no stable tag exists at all.
    """
    PRERELEASE = re.compile(
        r"(beta|alpha|rc|pre|dev|nightly|snapshot|canary|wip)", re.IGNORECASE
    )
    try:
        r = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", f"https://{host}/{owner}/{repo}.git"],
            capture_output=True,
            text=True,
            timeout=30,
            env=GIT_ENV,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        tags = []
        for line in r.stdout.strip().split("\n"):
            if "refs/tags/" in line:
                tag = line.split("refs/tags/")[-1].strip()
                # skip junk tags
                if tag and len(tag) < 60 and "%" not in tag:
                    tags.append(tag)
        if not tags:
            return None
        stable = [t for t in tags if not PRERELEASE.search(t)]
        pool = stable if stable else tags
        return max(pool, key=version_sort_key)
    except Exception:
        return None


def latest_commit_date_via_api(owner, repo, headers, host="github.com"):
    """Date of the latest commit on the default branch as 'YYYYMMDD'.

    Used for repos without releases/tags whose package version is a date.
    """
    if host == "github.com":
        api_url = f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=1"

        def date_path(c):
            return c.get("commit", {}).get("committer", {}).get("date", "")
    else:  # gitlab.com
        api_url = (
            f"https://gitlab.com/api/v4/projects/{owner}%2F{repo}"
            "/repository/commits?per_page=1"
        )

        def date_path(c):
            return c.get("committed_date", "")
    data = fetch_json(api_url, headers=headers)
    if data and isinstance(data, list) and data:
        date_str = date_path(data[0])
        if date_str:
            try:
                dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
                return dt.strftime("%Y%m%d")
            except ValueError:
                return None
    return None


def get_upstream_version(pkg):
    """Determine upstream version for a package.

    Returns (version, reason, release_url) tuple.
    """
    url = pkg.get("url", "")
    vcs = pkg.get("vcs", "")
    name = pkg["name"]

    if not url and not vcs:
        return None, "no_url_vcs", None

    # PyPI packages
    if "pypi.org" in url or "pypi.python.org" in url:
        pypi_name = name.replace("python3-module-", "").replace("python-", "")
        if url.startswith("https://pypi.org/project/"):
            pypi_name = url.split("/project/")[-1].rstrip("/")
        data = fetch_json(f"https://pypi.org/pypi/{pypi_name}/json")
        if data and "info" in data:
            return data["info"].get("version"), None, f"https://pypi.org/project/{pypi_name}/"
        return None, f"pypi_failed:{pypi_name}", None

    # crates.io packages
    if "crates.io" in url:
        crate_name = url.split("/crates/")[-1].rstrip("/")
        data = fetch_json(f"https://crates.io/api/v1/crates/{crate_name}")
        if data and "crate" in data:
            return data["crate"].get("newest_version"), None, f"https://crates.io/crates/{crate_name}"
        return None, f"crates_failed:{crate_name}", None

    # GitHub releases
    if "github.com" in vcs or "github.com" in url:
        gh_url = vcs if "github.com" in vcs else url
        match = re.search(r"github\.com/([^/]+)/([^/]+)", gh_url)
        if match:
            owner, repo = match.group(1), match.group(2).replace(".git", "").rstrip("/")
            headers = {"User-Agent": "altlinux-outdated-checker"}
            if github_token:
                headers["Authorization"] = f"token {github_token}"
            # Compare the API release with tags: /latest may lag behind tags.
            data = fetch_json(
                f"https://api.github.com/repos/{owner}/{repo}/releases/latest",
                headers=headers,
            )
            release_tag = data.get("tag_name") if isinstance(data, dict) else None
            git_tag = latest_tag_via_git("github.com", owner, repo)
            candidates = [t for t in (release_tag, git_tag) if t]
            if candidates:
                tag = max(candidates, key=version_sort_key)
                return tag.lstrip("v"), None, f"https://github.com/{owner}/{repo}/releases/tag/{tag}"
            # Fallback: latest commit date (packages versioned by date)
            date = latest_commit_date_via_api(owner, repo, headers)
            if date:
                return date, None, f"https://github.com/{owner}/{repo}/commits"
            return None, f"github_no_release:{owner}/{repo}", None
        return None, f"github_parse_fail:{gh_url}", None

    # GitLab releases
    if "gitlab.com" in vcs or "gitlab.com" in url:
        gl_url = vcs if "gitlab.com" in vcs else url
        match = re.search(r"gitlab\.com/([^/]+)/([^/]+)", gl_url)
        if match:
            owner, repo = match.group(1), match.group(2).replace(".git", "").rstrip("/")
            # Try releases API first
            data = fetch_json(f"https://gitlab.com/api/v4/projects/{owner}%2F{repo}/releases")
            release_tags = (
                [release.get("tag_name") for release in data if isinstance(release, dict)]
                if isinstance(data, list) else []
            )
            git_tag = latest_tag_via_git("gitlab.com", owner, repo)
            candidates = [t for t in (*release_tags, git_tag) if t]
            if candidates:
                tag = max(candidates, key=version_sort_key)
                return tag.lstrip("v"), None, f"https://gitlab.com/{owner}/{repo}/-/releases/{tag}"
            # Fallback: latest commit date (packages versioned by date)
            date = latest_commit_date_via_api(owner, repo, {}, host="gitlab.com")
            if date:
                return date, None, f"https://gitlab.com/{owner}/{repo}/-/commits"
            return None, f"gitlab_no_release:{owner}/{repo}", None
        return None, f"gitlab_parse_fail:{gl_url}", None

    return None, f"unsupported_source:{url or vcs}", None


def load_previous_state(include_versions=False):
    """Load previous report names and, optionally, upstream versions."""
    if Path(STATE_FILE).exists():
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
                names = set(data.get("outdated", []))
                versions = data.get("upstream_versions", {})
                return (names, versions) if include_versions else names
        except Exception as e:
            logger.warning(f"Failed to load previous state: {e}")
    return (set(), {}) if include_versions else set()


def save_current_state(outdated_names, upstream_versions=None):
    """Save reported outdated names and their upstream versions."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump({
                "outdated": sorted(outdated_names),
                "upstream_versions": upstream_versions or {},
            }, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save state: {e}")


def _utf16_len(s):
    """String length in UTF-16 code units — Telegram entity offsets use these."""
    return len(s.encode("utf-16-le")) // 2


def build_report_segments(outdated, previous_names=None, error_names=None):
    """Build the report as (text, entity_type, url) segments.

    entity_type: "bold" / "code" / "text_link" (requires url); None = plain.
    """
    segments = []
    outdated = sorted(
        outdated, key=lambda x: x.get("pkg_name", x["name"]).lower()
    )
    now = datetime.now().strftime("%Y-%m-%d")

    if not outdated:
        segments.append(("✅ ", None, None))
        segments.append(("ALT Linux Sisyphus — все пакеты актуальны!", "bold", None))
        segments.append((f"\nМейнтейнер: {maintainer_nickname}\nДата: {now}", None, None))
    else:
        segments.append(("📦 ", None, None))
        segments.append(("ALT Linux Sisyphus — устаревшие пакеты", "bold", None))
        segments.append(
            (f"\nМейнтейнер: {maintainer_nickname}\nДата: {now}\nВсего: {len(outdated)}\n\n", None, None)
        )
        for pkg in outdated:
            pkg_name = pkg.get("pkg_name", pkg["name"])
            segments.append(("• ", None, None))
            segments.append((pkg_name, "code", None))
            segments.append((": ", None, None))
            segments.append(
                (
                    pkg["alt_version"],
                    "text_link",
                    f"https://packages.altlinux.org/ru/sisyphus/srpms/{pkg_name}/",
                )
            )
            segments.append((" → ", None, None))
            segments.append((pkg["upstream_version"], "text_link", pkg.get("upstream_url")))
            if pkg.get("previous_upstream_version"):
                segments.append((
                    f" (в прошлом отчёте: {pkg['previous_upstream_version']})",
                    None, None,
                ))
            segments.append(("\n", None, None))

    if previous_names:
        current = {p.get("pkg_name", p["name"]) for p in outdated}
        added = sorted(current - previous_names)
        removed = sorted(previous_names - current)
        if added:
            segments.append(("\n🔴 ", None, None))
            segments.append((f"Новые устаревшие ({len(added)}):", "bold", None))
            for name in added:
                segments.append(("\n  + ", None, None))
                segments.append((name, "code", None))
        if removed:
            prefix = "\n\n🟢 " if added else "\n🟢 "
            segments.append((prefix, None, None))
            segments.append((f"Исправлены ({len(removed)}):", "bold", None))
            for name in removed:
                segments.append(("\n  − ", None, None))
                segments.append((name, "code", None))
        if not added and not removed and not any(
            p.get("previous_upstream_version") for p in outdated
        ):
            segments.append(("\n⚪ ", None, None))
            segments.append(("Без изменений с прошлого отчёта", "bold", None))

    if error_names:
        # diff-секция не заканчивается переводом строки — нужен ещё один \n
        prefix = "\n\n⚠️ " if previous_names else "\n⚠️ "
        segments.append((prefix, None, None))
        segments.append(
            (f"Не удалось получить версию ({len(error_names)}):", "bold", None)
        )
        for name in sorted(error_names, key=str.lower):
            segments.append(("\n  ! ", None, None))
            segments.append((name, "code", None))

    return segments


def assemble_message(segments):
    """Fold (text, type, url) segments into (text, entities) with UTF-16 offsets."""
    text = ""
    entities = []
    for s, etype, url in segments:
        if not s:
            continue
        if etype == "text_link" and not url:
            etype = None  # nothing to link to — send as plain text
        offset = _utf16_len(text)
        text += s
        if etype:
            ent = {"type": etype, "offset": offset, "length": _utf16_len(s)}
            if etype == "text_link":
                ent["url"] = url
            entities.append(ent)
    return text, entities


def send_message(text, parse_mode="HTML", entities=None):
    """Send message via telebot.

    If `entities` is provided, the message goes out as plain text plus a
    MessageEntity list (offsets in UTF-16 code units) and parse_mode is
    ignored. Link URLs inside entities do not count toward the 4096-char
    text limit.
    """
    try:
        kwargs: dict = {
            "disable_web_page_preview": True,
        }
        if entities is not None:
            kwargs["entities"] = [
                MessageEntity(
                    type=e["type"],
                    offset=e["offset"],
                    length=e["length"],
                    url=e.get("url"),
                )
                for e in entities
            ]
        else:
            kwargs["parse_mode"] = parse_mode
        BOT_INSTANCE.send_message(telegram_user_id, text, **kwargs)
        logger.info("Telegram message sent")
        return True
    except Exception as e:
        logger.exception(f"Failed to send Telegram message: {e}")
        return False


def send_report(outdated, previous_names=None, error_names=None):
    """Send whole report lines, respecting text and formatting limits."""
    segments = build_report_segments(outdated, previous_names, error_names)
    lines = []
    line = []
    for text, entity_type, url in segments:
        for part in text.splitlines(keepends=True):
            line.append((part, entity_type, url))
            if part.endswith("\n"):
                lines.append(line)
                line = []
    if line:
        lines.append(line)

    chunks = []
    chunk = []
    for line in lines:
        line_text, line_entities = assemble_message(line)
        if _utf16_len(line_text) > 4000 or len(line_entities) > 90:
            logger.error("Report line exceeds Telegram limits; refusing to split it")
            return False
        candidate_text, candidate_entities = assemble_message(chunk + line)
        if chunk and (
            len(candidate_entities) > 90 or _utf16_len(candidate_text) > 4000
        ):
            chunks.append(assemble_message(chunk))
            chunk = []
        chunk.extend(line)
    if chunk:
        chunks.append(assemble_message(chunk))

    success = True
    for text, entities in chunks:
        success = send_message(text, entities=entities) and success
    return success


def send_report_chunked(outdated, error_names=None):
    """Chunked sender — used only when the plain report text alone exceeds
    Telegram's message limit (hundreds of outdated packages)."""
    outdated = sorted(
        outdated, key=lambda x: x.get("pkg_name", x["name"]).lower()
    )
    now = datetime.now().strftime("%Y-%m-%d")

    if not outdated:
        return send_message(
            f"✅ <b>ALT Linux Sisyphus — все пакеты актуальны!</b>\n"
            f"Мейнтейнер: {maintainer_nickname}\nДата: {now}"
        )

    header = (
        f"📦 <b>ALT Linux Sisyphus — устаревшие пакеты</b>\n"
        f"Мейнтейнер: {maintainer_nickname}\nДата: {now}\nВсего: {len(outdated)}\n"
    )

    lines = []
    for pkg in outdated:
        pkg_name = pkg.get("pkg_name", pkg["name"])
        name = pkg_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        alt = pkg["alt_version"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        up = pkg["upstream_version"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        pkg_url = f"https://packages.altlinux.org/ru/sisyphus/srpms/{pkg_name}/"
        up_url = pkg.get("upstream_url")
        alt_link = f'<a href="{pkg_url}">{alt}</a>'
        up_link = f'<a href="{up_url}">{up}</a>' if up_url else up
        suffix = ""
        if pkg.get("previous_upstream_version"):
            previous = (pkg["previous_upstream_version"].replace("&", "&amp;")
                        .replace("<", "&lt;").replace(">", "&gt;"))
            suffix = f" (в прошлом отчёте: {previous})"
        lines.append(f"• <code>{name}</code>: {alt_link} → {up_link}{suffix}")

    error_lines = []
    if error_names:
        error_lines.append(
            f"\n⚠️ <b>Не удалось получить версию ({len(error_names)}):</b>"
        )
        for name in sorted(error_names, key=str.lower):
            error_lines.append(f"  ! <code>{name}</code>")

    success = send_message(header)
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 4000:
            success = send_message(chunk) and success
            chunk = line + "\n"
        else:
            chunk += line + "\n"
    if chunk or error_lines:
        success = send_message(chunk + "\n".join(error_lines)) and success

    return success


def bot(save_state=True):
    logger.info("Updating specs repository...")
    update_specs()

    logger.info("Fetching maintainer packages...")
    packages = get_maintainer_packages()
    logger.info(f"Found {len(packages)} packages")

    outdated = []
    errors = []

    for i, pkg in enumerate(packages):
        pkg_name = pkg.get("pkg_name", pkg["name"])
        upstream, reason, up_url = get_upstream_version(pkg)

        if upstream:
            is_outdated = compare_versions(pkg["alt_version"], upstream)
            status = "<red>OUTDATED</>" if is_outdated else "<green>up to date</>"
            logger.opt(colors=True).debug(
                f"<white>[{i + 1}/{len(packages)}]</white> "
                f"<blue>{pkg_name}</blue><white>: "
                f"ALT: {pkg['alt_version']} | Upstream: {upstream} | </white>" + status
            )
            if is_outdated:
                outdated.append({**pkg, "upstream_version": upstream, "upstream_url": up_url})
        else:
            logger.warning(f"{pkg_name}: could not determine upstream version ({reason})")
            errors.append(pkg_name)

    logger.info(f"Outdated packages: {len(outdated)}")
    logger.info(f"Errors: {len(errors)}")

    # Diff with previous run
    previous_names, previous_versions = load_previous_state(include_versions=True)
    # Migrate names saved by older versions, which used upstream/module names.
    repository_names = {pkg["name"]: pkg.get("pkg_name", pkg["name"]) for pkg in packages}
    previous_names = {repository_names.get(name, name) for name in previous_names}
    current_names = {pkg.get("pkg_name", pkg["name"]) for pkg in outdated}
    current_versions = {}
    for pkg in outdated:
        key = pkg.get("pkg_name", pkg["name"])
        current_versions[key] = pkg["upstream_version"]
        previous = previous_versions.get(key)
        if previous and previous != pkg["upstream_version"]:
            pkg["previous_upstream_version"] = previous

    sent = send_report(outdated, previous_names or None, errors or None)

    # Compare against the last successfully sent report, not an unsent run.
    if save_state and sent:
        save_current_state(current_names, current_versions)


def main():
    parser = argparse.ArgumentParser(
        description="ALT Linux outdated packages watcher"
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="run the check immediately and exit (no schedule)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="do not overwrite the saved state (diff history stays intact)",
    )
    args = parser.parse_args()

    if args.now:
        bot(save_state=not args.no_save)
        return

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
