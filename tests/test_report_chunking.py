"""Verify Telegram chunks preserve entire package rows and entity offsets."""
import ast
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock


class ReportChunkingTests(unittest.TestCase):
    def test_whole_lines_for_both_limits(self):
        source = Path(__file__).resolve().parents[1] / "packages_bot.py"
        tree = ast.parse(source.read_text())
        names = {"_utf16_len", "build_report_segments", "assemble_message", "send_report"}
        module = ast.Module(body=[
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in names
        ], type_ignores=[])
        for count, name_length in [(45, 10), (20, 300)]:
            with self.subTest(count=count, name_length=name_length):
                sender = Mock(return_value=True)
                ns = {"datetime": datetime, "maintainer_nickname": "tester",
                      "send_message": sender, "logger": Mock()}
                exec(compile(module, str(source), "exec"), ns)  # noqa: S102
                packages = [
                    {"name": f"pkg-{i:03d}-" + "x" * name_length,
                     "alt_version": "1.0", "upstream_version": "2.0",
                     "upstream_url": "https://example.org", "previous_upstream_version": "1.5",
                     "prerelease_version": "3.0-beta.1", "prerelease_url": "https://example.org/beta"}
                    for i in range(count)
                ]
                segments = ns["build_report_segments"](packages, {"old"}, {"error"})
                expected, _ = ns["assemble_message"](segments)
                self.assertTrue(ns["send_report"](packages, {"old"}, {"error"}))
                self.assertGreater(sender.call_count, 1)
                messages = [call.args[0] for call in sender.call_args_list]
                self.assertEqual("".join(messages), expected)
                for call in sender.call_args_list:
                    text = call.args[0]
                    entities = call.kwargs["entities"]
                    self.assertLessEqual(ns["_utf16_len"](text), 4000)
                    self.assertLessEqual(len(entities), 90)
                    for entity in entities:
                        self.assertLessEqual(entity["offset"] + entity["length"],
                                             ns["_utf16_len"](text))
                for package in packages:
                    row = (f"• {package['name']}: 1.0 → 2.0; prerelease: 3.0-beta.1"
                           " (в прошлом отчёте: 1.5)\n")
                    self.assertEqual(sum(row in message for message in messages), 1)


if __name__ == "__main__":
    unittest.main()
