"""Regression tests for report section spacing."""
import ast
import unittest
from datetime import datetime
from pathlib import Path


class ReportSpacingTests(unittest.TestCase):
    def test_blank_line_between_added_and_removed(self):
        source = Path(__file__).resolve().parents[1] / "packages_bot.py"
        tree = ast.parse(source.read_text())
        module = ast.Module(body=[
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "build_report_segments"
        ], type_ignores=[])
        ns = {"datetime": datetime, "maintainer_nickname": "tester"}
        # Execute only a selected function from trusted local source.
        exec(compile(module, str(source), "exec"), ns)  # noqa: S102
        for previous in ({"old"}, {"new", "old"}):
            with self.subTest(previous=previous):
                segments = ns["build_report_segments"]([
                    {"name": "new", "alt_version": "1", "upstream_version": "2"},
                ], previous)
                text = "".join(segment[0] for segment in segments)
                if "new" not in previous:
                    self.assertIn("  + new\n\n🟢 Исправлены", text)
                else:
                    self.assertIn("2\n\n🟢 Исправлены", text)
                    self.assertNotIn("2\n\n\n🟢", text)


if __name__ == "__main__":
    unittest.main()
