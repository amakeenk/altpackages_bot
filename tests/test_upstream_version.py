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
             "version_without_release", "is_date_version"}
    module = ast.Module(
        body=[node for node in tree.body
              if isinstance(node, ast.FunctionDef) and node.name in names],
        type_ignores=[],
    )
    namespace = {
        "re": re, "github_token": "", "datetime": datetime,
        "source_version": Mock(return_value=None),
        "fetch_json": Mock(), "latest_tag_via_git": Mock(),
        "latest_commit_date_via_api": Mock(return_value=None),
    }
    # Execute only selected functions from the trusted local source file.
    exec(compile(module, str(source), "exec"), namespace)  # noqa: S102
    return namespace


class UpstreamVersionTests(unittest.TestCase):
    def check_detection(self, host, releases, git_tag, expected):
        ns = detection_namespace()
        ns["fetch_json"].return_value = releases
        ns["latest_tag_via_git"].return_value = git_tag
        result = ns["get_upstream_version"]({
            "name": "influxdb3", "vcs": f"https://{host}/influxdata/influxdb.git",
        })
        self.assertEqual(result[0], expected)
        self.assertIsNone(result[1])
        if expected:
            self.assertTrue(result[2].endswith(f"/v{expected}"))
        ns["latest_tag_via_git"].assert_called_once_with(host, "influxdata", "influxdb")

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
