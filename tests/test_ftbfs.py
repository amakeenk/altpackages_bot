"""Beehive parsing and standalone Telegram report tests."""
import argparse
import ast
import sys
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch


class FtbfsTests(unittest.TestCase):
    def namespace(self):
        source = Path(__file__).resolve().parents[1] / "packages_bot.py"
        tree = ast.parse(source.read_text())
        names = {"parse_ftbfs", "get_ftbfs_packages", "send_ftbfs_report",
                 "send_segments", "assemble_message", "_utf16_len", "main"}
        module = ast.Module(body=[n for n in tree.body
                                  if isinstance(n, ast.FunctionDef) and n.name in names],
                            type_ignores=[])
        ns = {"urllib": urllib, "argparse": argparse, "sys": sys,
              "datetime": datetime, "maintainer_nickname": "amakeenk",
              "BEEHIVE_BASE": "https://git.altlinux.org/beehive",
              "BEEHIVE_TARGET": "Sisyphus-x86_64", "logger": Mock(),
              "send_message": Mock(return_value=True)}
        exec(compile(module, str(source), "exec"), ns)  # noqa: S102
        return ns

    def test_cli_ftbfs_only(self):
        ns = self.namespace()
        ns["get_ftbfs_packages"] = Mock(return_value=[])
        ns["send_ftbfs_report"] = Mock(return_value=True)
        ns["bot"] = Mock()
        with patch.object(sys, "argv", ["packages_bot.py", "--ftbfs"]):
            ns["main"]()
        ns["get_ftbfs_packages"].assert_called_once_with()
        ns["send_ftbfs_report"].assert_called_once_with([])
        ns["bot"].assert_not_called()
        ns["send_message"].assert_not_called()

    def test_cli_ftbfs_failure_exit_code(self):
        for packages, sent in [(None, True), ([], False)]:
            with self.subTest(packages=packages, sent=sent):
                ns = self.namespace()
                ns["get_ftbfs_packages"] = Mock(return_value=packages)
                ns["send_ftbfs_report"] = Mock(return_value=sent)
                with (
                    patch.object(sys, "argv", ["packages_bot.py", "--ftbfs"]),
                    self.assertRaises(SystemExit) as error,
                ):
                    ns["main"]()
                self.assertEqual(error.exception.code, 1)
                if packages is None:
                    ns["send_ftbfs_report"].assert_not_called()

    def test_exact_acl_and_log_url(self):
        ns = self.namespace()
        packages = ns["parse_ftbfs"](
            "ollama\t0.35.0-alt1\t0\tarmatik,amakeenk,@everybody\n"
            "other\t1-alt1\t1\tamakeenk2,@everybody\n"
            "yq-go\t4.53.3-alt1\t0\tamakeenk,dmaks,@everybody\n", "amakeenk")
        self.assertEqual([p["name"] for p in packages], ["ollama", "yq-go"])
        self.assertEqual(packages[0]["log_url"],
                         "https://git.altlinux.org/beehive/logs/Sisyphus-x86_64/latest/error/ollama-0.35.0-alt1")
        self.assertTrue(ns["send_ftbfs_report"](packages))
        call = ns["send_message"].call_args
        self.assertIn("ollama-0.35.0-alt1 — лог сборки", call.args[0])
        links = [e for e in call.kwargs["entities"] if e["type"] == "text_link"]
        self.assertEqual([e["url"] for e in links], [
            url for p in packages for url in (
                f"https://packages.altlinux.org/ru/sisyphus/srpms/{p['name']}/", p["log_url"],
            )
        ])
        encoded = call.args[0].encode("utf-16-le")
        label = encoded[links[0]["offset"] * 2:
                        (links[0]["offset"] + links[0]["length"]) * 2].decode("utf-16-le")
        self.assertEqual(label, "ollama-0.35.0-alt1")

    def test_fetch_error_is_not_empty_success(self):
        ns = self.namespace()
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            self.assertIsNone(ns["get_ftbfs_packages"]())
        ns["logger"].warning.assert_called_once()
        ns["send_message"].assert_not_called()

    def test_empty_and_invalid_input(self):
        ns = self.namespace()
        self.assertEqual(ns["parse_ftbfs"]("", "amakeenk"), [])
        with self.assertRaises(ValueError):
            ns["parse_ftbfs"]("<html>error</html>", "amakeenk")
        self.assertTrue(ns["send_ftbfs_report"]([]))
        self.assertIn("Непересобирающихся пакетов нет", ns["send_message"].call_args.args[0])

    def test_large_report_keeps_rows_intact(self):
        ns = self.namespace()
        packages = [{"name": f"pkg-{i:03d}", "version": "1-alt1",
                     "log_url": f"https://example.org/{i}"} for i in range(100)]
        self.assertTrue(ns["send_ftbfs_report"](packages))
        calls = ns["send_message"].call_args_list
        self.assertGreater(len(calls), 1)
        for call in calls:
            self.assertLessEqual(len(call.kwargs["entities"]), 90)
            self.assertLessEqual(ns["_utf16_len"](call.args[0]), 4000)
        for pkg in packages:
            row = f"• {pkg['name']}-1-alt1 — лог сборки\n"
            self.assertEqual(sum(row in call.args[0] for call in calls), 1)


if __name__ == "__main__":
    unittest.main()
