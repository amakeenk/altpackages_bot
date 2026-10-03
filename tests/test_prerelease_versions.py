"""Stable and prerelease channels are selected independently."""
import ast
import re
import unittest
from pathlib import Path
from unittest.mock import Mock


class PrereleaseVersionTests(unittest.TestCase):
    def namespace(self):
        source = Path(__file__).resolve().parents[1] / "packages_bot.py"
        tree = ast.parse(source.read_text())
        names = {"normalize_version", "is_prerelease", "version_sort_key",
                 "compare_versions", "get_upstream_candidates", "format_upstream_candidates"}
        module = ast.Module(body=[n for n in tree.body
                                  if isinstance(n, ast.FunctionDef) and n.name in names],
                            type_ignores=[])
        ns = {"re": re, "fetch_json": Mock()}
        exec(compile(module, str(source), "exec"), ns)  # noqa: S102
        return ns

    def test_comparison(self):
        ns = self.namespace()
        for older, newer in [
            ("3.0.0-beta.617", "3.0.0"), ("3.0.0-beta.9", "3.0.0-beta.10"),
            ("3.0.0-beta.617", "3.0.0-rc.1"), ("2.5.308", "3.0.0-beta.617"),
            ("0.107.99", "0.108.0-beta.1"), ("1.0", "1.0.1"),
        ]:
            with self.subTest(older=older, newer=newer):
                self.assertTrue(ns["compare_versions"](older, newer))
                self.assertFalse(ns["compare_versions"](newer, older))
        self.assertFalse(ns["compare_versions"]("1.0", "1.0.0"))
        self.assertEqual(ns["version_sort_key"]("0.108.0.b.90"),
                         ns["version_sort_key"]("0.108.0-beta.90"))
        self.assertTrue(ns["compare_versions"]("0.108.0.b.90", "1.0.0-b.1"))
        self.assertTrue(ns["is_prerelease"]("1.0.0-b.1"))
        self.assertTrue(ns["is_prerelease"]("0.108.0.b.90"))

    def test_git_channels_and_alt_floor(self):
        for alt, stable, prerelease, expected in [
            ("2.5.308", "2.5.309", "3.0.0-beta.617", {"stable", "prerelease"}),
            ("0.108.0-beta.1", "0.107.99", "0.108.0-beta.2", {"prerelease"}),
            ("0.108.0-beta.1", "1.0.0", "1.1.0-beta.1", {"stable", "prerelease"}),
        ]:
            with self.subTest(alt=alt):
                ns = self.namespace()
                ns["get_upstream_version"] = Mock(return_value=(prerelease, None, "url"))
                ns["latest_tag_via_git"] = Mock(side_effect=["v" + stable, "v" + prerelease])
                candidates, _ = ns["get_upstream_candidates"]({
                    "name": "pkg", "vcs": "https://github.com/owner/repo.git",
                })
                self.assertEqual(candidates["stable"][0], stable)
                self.assertEqual(candidates["prerelease"][0], prerelease)
                newer = {channel for channel, value in candidates.items()
                         if value and ns["compare_versions"](alt, value[0])}
                self.assertEqual(newer, expected)

    def test_logs_hide_older_prereleases(self):
        ns = self.namespace()
        for alt, stable, prerelease in [
            ("4.39.20", "4.39.28", "4.0.0-alpha2"),
            ("0.3.3", "0.4.0", "0.3.2-alpha3"),
            ("0.18.7", "0.21.0", "0.12.0-beta2"),
            ("0.14.9", "0.14.9", "0.1.0-alpha-4"),
            ("1.7.7", "1.8.1", "1.8.0-rc2"),
            ("1.7.7", "1.8.0", "1.8.0-rc2"),
        ]:
            with self.subTest(alt=alt):
                result = ns["format_upstream_candidates"]({
                    "stable": (stable, "url"), "prerelease": (prerelease, "url"),
                }, alt)
                self.assertEqual(result, f"stable: {stable}")
        self.assertEqual(ns["format_upstream_candidates"]({
            "stable": ("1.5.6-stable", "url"), "prerelease": ("2.1.0-beta", "url"),
        }, "1.5.0"), "stable: 1.5.6-stable | prerelease: 2.1.0-beta")
        self.assertEqual(ns["format_upstream_candidates"]({
            "stable": ("0.107.99", "url"), "prerelease": ("1.0.0-b.1", "url"),
        }, "0.108.0.b.90"), "prerelease: 1.0.0-b.1")

    def test_stable_supersedes_prerelease_in_candidates(self):
        for stable in ("1.8.1", "1.8.0"):
            with self.subTest(stable=stable):
                ns = self.namespace()
                ns["get_upstream_version"] = Mock(return_value=(stable, None, "url"))
                ns["latest_tag_via_git"] = Mock(side_effect=["v" + stable, "v1.8.0-rc2"])
                candidates, _ = ns["get_upstream_candidates"]({
                    "name": "crowdsec", "vcs": "https://github.com/crowdsecurity/crowdsec",
                })
                self.assertEqual(candidates["stable"][0], stable)
                self.assertIsNone(candidates["prerelease"])

    def test_pypi_yanked_versions_excluded(self):
        ns = self.namespace()
        ns["get_upstream_version"] = Mock(return_value=("1.0", None, "url"))
        ns["fetch_json"].return_value = {"releases": {
            "1.1": [{"yanked": False}], "2.0b1": [{"yanked": False}],
            "3.0b1": [{"yanked": True}],
        }}
        candidates, _ = ns["get_upstream_candidates"]({
            "name": "pkg", "url": "https://pypi.org/project/pkg/",
        })
        self.assertEqual(candidates["stable"][0], "1.1")
        self.assertEqual(candidates["prerelease"][0], "2.0b1")


if __name__ == "__main__":
    unittest.main()
