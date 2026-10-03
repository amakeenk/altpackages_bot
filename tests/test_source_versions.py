"""Conservative source-metadata fallback, without executing upstream code."""
import ast
import base64
import configparser
import json
import re
import unittest
import urllib.parse
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import toml


class SourceVersionTests(unittest.TestCase):
    def namespace(self, files=None):
        source = Path(__file__).resolve().parents[1] / "packages_bot.py"
        tree = ast.parse(source.read_text())
        names = {"is_date_version", "source_manifest", "source_version", "version_without_release"}
        module = ast.Module(body=[n for n in tree.body
                                  if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
        ns = {"re": re, "json": json, "toml": toml, "base64": base64,
              "configparser": configparser, "urllib": urllib, "datetime": datetime,
              "version_files": {}, "logger": Mock(),
              "latest_commit_date_via_api": Mock(return_value="20261002")}
        files = files or {}

        def fetch(url, headers=None):
            path = urllib.parse.unquote(url.split("/contents/")[-1])
            if path not in files:
                return {"message": "Not Found"}
            return {"encoding": "base64", "content": base64.b64encode(files[path].encode()).decode(),
                    "html_url": "https://github.com/owner/repo/blob/main/" + path}

        ns["fetch_json"] = Mock(side_effect=fetch)
        exec(compile(module, str(source), "exec"), ns)  # noqa: S102
        return ns

    def test_semver_never_uses_commit_date(self):
        ns = self.namespace()
        result = ns["version_without_release"]({"name": "pkg", "alt_version": "0.13.1"},
                                                "github.com", "owner", "repo", {})
        self.assertIsNone(result[0])
        ns["latest_commit_date_via_api"].assert_not_called()

    def test_valid_date_formats(self):
        for version, expected in [("20250101", "20261002"), ("2025.01.01", "2026.10.02"),
                                  ("2025-01-01", "2026-10-02")]:
            ns = self.namespace()
            result = ns["version_without_release"]({"name": "pkg", "alt_version": version},
                                                    "github.com", "owner", "repo", {})
            self.assertEqual(result[0], expected)
            ns["fetch_json"].assert_not_called()
        self.assertFalse(ns["is_date_version"]("20251399"))

    def test_workspace_matching_and_inheritance(self):
        ns = self.namespace({
            "Cargo.toml": '[workspace]\nmembers = ["aw-server", "aw-sync"]\n[workspace.package]\nversion = "0.14.0"',
            "aw-server/Cargo.toml": '[package]\nname = "aw-server"\nversion.workspace = true',
            "aw-sync/Cargo.toml": '[package]\nname = "aw-sync"\nversion = "0.1.0"',
        })
        pkg = {"name": "activitywatch-server-rust", "alt_version": "0.13.1"}
        result = ns["version_without_release"](pkg, "github.com", "ActivityWatch", "aw-server-rust", {})
        self.assertEqual(result[0], "0.14.0")
        self.assertTrue(pkg["upstream_source"])
        ns["latest_commit_date_via_api"].assert_not_called()

    def test_manifest_formats_and_dynamic_versions(self):
        ns = self.namespace()
        for path, content, expected in [
            ("package.json", '{"name":"pkg","version":"1.2.3"}', "1.2.3"),
            ("pyproject.toml", '[project]\nname="pkg"\nversion="1.2.3"', "1.2.3"),
            ("setup.cfg", '[metadata]\nname = pkg\nversion = 1.2.3', "1.2.3"),
            ("pyproject.toml", '[project]\nname="pkg"\ndynamic=["version"]', None),
        ]:
            with self.subTest(path=path):
                self.assertEqual(ns["source_manifest"](content, path)[1], expected)

    def test_conflicting_roots_are_not_guessed(self):
        ns = self.namespace({"Cargo.toml": '[package]\nname="pkg"\nversion="1.0"',
                             "package.json": '{"name":"pkg","version":"2.0"}'})
        pkg = {"name": "pkg"}
        self.assertIsNone(ns["source_version"](pkg, "github.com", "owner", "repo", {}))
        ns["version_files"] = {"pkg": "package.json"}
        self.assertEqual(ns["source_version"](pkg, "github.com", "owner", "repo", {})[0], "2.0")


if __name__ == "__main__":
    unittest.main()
