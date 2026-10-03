"""Package selection tests without bot credentials or network access."""
import ast
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock


class PackageSelectionTests(unittest.TestCase):
    def test_extra_packages_and_ignore_priority(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {}
            for name in ("own", "foreign", "ignored"):
                spec = root / name[0] / name / "upstream.spec"
                spec.parent.mkdir(parents=True)
                spec.write_text(
                    "Name: upstream-name\nVersion: 1.0\nURL: https://example.org\n"
                )
                paths[name] = str(spec)
            source = Path(__file__).resolve().parents[1] / "packages_bot.py"
            tree = ast.parse(source.read_text())
            module = ast.Module(body=[
                node for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and node.name == "get_maintainer_packages"
            ], type_ignores=[])
            logger = Mock()
            ns = {
                "Path": Path, "re": re, "SPECS_DIR": directory,
                "maintainer_nickname": "maintainer", "logger": logger,
                "ignore_packages": ["ignored"],
                "extra_packages": ["own", "foreign", "foreign", "ignored", "missing"],
                "run": Mock(return_value=Mock(stdout=paths["own"] + "\n")),
            }
            # Execute only a selected function from trusted local source.
            exec(compile(module, str(source), "exec"), ns)  # noqa: S102
            packages = ns["get_maintainer_packages"]()
            self.assertEqual(sorted(p["pkg_name"] for p in packages), ["foreign", "own"])
            self.assertTrue(all(p["name"] == "upstream-name" for p in packages))
            logger.warning.assert_called_once_with("Extra package not found in specs: missing")
            ns["extra_packages"] = []
            self.assertEqual([p["pkg_name"] for p in ns["get_maintainer_packages"]()], ["own"])


if __name__ == "__main__":
    unittest.main()
