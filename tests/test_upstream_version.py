"""Test detection without loading bot credentials or starting Telegram."""
import ast
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock


def detection_namespace():
    import re

    source = Path(__file__).resolve().parents[1] / "packages_bot.py"
    tree = ast.parse(source.read_text())
    names = {"normalize_version", "is_prerelease", "version_sort_key", "get_upstream_version",
             "version_without_release", "is_date_version", "version_from_tag"}
    module = ast.Module(
        body=[node for node in tree.body
              if isinstance(node, ast.FunctionDef) and node.name in names],
        type_ignores=[],
    )
    namespace = {
        "re": re, "github_token": "", "datetime": datetime,
        "urllib": __import__("urllib"),
        "source_version": Mock(return_value=None),
        "fetch_json": Mock(), "latest_tag_via_git": Mock(),
        "latest_commit_date_via_api": Mock(return_value=None),
    }
    # Execute only selected functions from the trusted local source file.
    exec(compile(module, str(source), "exec"), namespace)  # noqa: S102
    return namespace


class UpstreamVersionTests(unittest.TestCase):
    def check_detection(self, host, releases, git_tag, expected, owner="influxdata", repo="influxdb"):
        ns = detection_namespace()
        ns["fetch_json"].return_value = releases
        ns["latest_tag_via_git"].return_value = git_tag
        result = ns["get_upstream_version"]({
            "name": "influxdb3", "vcs": f"https://{host}/{owner}/{repo}.git",
        })
        self.assertEqual(result[0], expected)
        self.assertIsNone(result[1])
        if expected:
            self.assertTrue(result[2].endswith(expected) or result[2].endswith(f"v{expected}"))
        ns["latest_tag_via_git"].assert_called_once()
        args, kwargs = ns["latest_tag_via_git"].call_args
        self.assertEqual(args[:3], (host, owner, repo))

    def test_github_sources(self):
        for release, tag, expected in [
            ("v3.11.4", "v3.12.0", "3.12.0"),
            ("v3.12.0", "v3.11.4", "3.12.0"),
            ("v3.12.0", None, "3.12.0"),
            (None, "v3.12.0", "3.12.0"),
            ("v3.9.0", "v3.12.0", "3.12.0"),
        ]:
            with self.subTest(release=release, tag=tag):
                self.check_detection("github.com", {"tag_name": release}, tag, expected)

    def test_gitlab_unsorted_releases(self):
        self.check_detection("gitlab.com", [
            {"tag_name": "v3.11.4"}, {"tag_name": "v3.13.0"},
        ], "v3.12.0", "3.13.0")

    def test_gitlab_api_error_still_checks_tags(self):
        self.check_detection("gitlab.com", {"message": "rate limited"},
                             "v3.12.0", "3.12.0")

    def test_self_hosted_gitlab_gnome(self):
        self.check_detection("gitlab.gnome.org", [{"tag_name": "v51.0"}],
                             "v51.0", "51.0", owner="donnybeelo", repo="convey")

    def test_self_hosted_gitlab_freedesktop(self):
        self.check_detection("gitlab.freedesktop.org", {"message": "not found"},
                             "v2.1.0", "2.1.0", owner="xorg", repo="lib" + "xcb")

    def test_ego_extension_by_pk(self):
        ns = detection_namespace()
        ns["fetch_json"].return_value = {
            "pk": 5592, "version": 12, "link": "/extension/5592/focused-window-d-bus/",
        }
        result = ns["get_upstream_version"]({
            "name": "gnome-shell-extension-focused-window-dbus",
            "url": "https://extensions.gnome.org/extension/5592/focused-window-d-bus",
            "vcs": "https://github.com/flexagoon/focused-window-dbus",
            "alt_version": "8",
        })
        self.assertEqual(result, ("12", None, "https://extensions.gnome.org/extension/5592/focused-window-d-bus/"))
        ns["fetch_json"].assert_called_once_with(
            "https://extensions.gnome.org/extension-info/?pk=5592&shell_version=51"
        )

    def test_scoped_npm_tag_biome(self):
        self.check_detection("github.com", {"tag_name": "@biomejs/biome@2.6.3"},
                             "@biomejs/biome@2.6.3", "2.6.3",
                             owner="biomejs", repo="biome")

    def test_no_sources_uses_commit_fallback(self):
        ns = detection_namespace()
        ns["fetch_json"].return_value = None
        ns["latest_tag_via_git"].return_value = None
        ns["latest_commit_date_via_api"].return_value = "20260910"
        result = ns["get_upstream_version"]({
            "name": "example", "alt_version": "20260101", "vcs": "https://github.com/owner/repo",
        })
        self.assertEqual(result, ("20260910", None, "https://github.com/owner/repo/commits"))


if __name__ == "__main__":
    unittest.main()
