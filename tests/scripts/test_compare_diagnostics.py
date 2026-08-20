import json
import os
import tempfile
import unittest
from typing import Any

from scripts.compare_diagnostics import compare_pyright, compare_ruff


class TestCompareDiagnostics(unittest.TestCase):
    test_dir: Any = None
    tmp_path: str = ""

    def setUp(self) -> None:
        self.test_dir = tempfile.TemporaryDirectory()
        self.tmp_path = self.test_dir.name

    def tearDown(self) -> None:
        if self.test_dir:
            self.test_dir.cleanup()

    def test_compare_ruff_unchanged(self) -> None:
        b_dir = os.path.join(self.tmp_path, "b")
        p_dir = os.path.join(self.tmp_path, "p")
        os.makedirs(b_dir, exist_ok=True)
        os.makedirs(p_dir, exist_ok=True)

        diag = [
            {
                "filename": os.path.join(b_dir, "foo.py"),
                "code": "E501",
                "message": "Line too long",
                "location": {"row": 1, "column": 1},
            }
        ]
        b_json = os.path.join(self.tmp_path, "b.json")
        p_json = os.path.join(self.tmp_path, "p.json")
        with open(b_json, "w") as f:
            json.dump(diag, f)

        diag_p = [
            {
                "filename": os.path.join(p_dir, "foo.py"),
                "code": "E501",
                "message": "Line too long",
                "location": {"row": 1, "column": 1},
            }
        ]
        with open(p_json, "w") as f:
            json.dump(diag_p, f)

        new_diags = compare_ruff(b_json, p_json, b_dir, p_dir, {})
        self.assertEqual(len(new_diags), 0)

    def test_compare_ruff_new_duplicate_location(self) -> None:
        b_dir = os.path.join(self.tmp_path, "b")
        p_dir = os.path.join(self.tmp_path, "p")
        os.makedirs(b_dir, exist_ok=True)
        os.makedirs(p_dir, exist_ok=True)

        diag = [
            {
                "filename": os.path.join(b_dir, "foo.py"),
                "code": "E501",
                "message": "Line too long",
                "location": {"row": 1, "column": 1},
            }
        ]
        b_json = os.path.join(self.tmp_path, "b.json")
        p_json = os.path.join(self.tmp_path, "p.json")
        with open(b_json, "w") as f:
            json.dump(diag, f)

        diag_p = [
            {
                "filename": os.path.join(p_dir, "foo.py"),
                "code": "E501",
                "message": "Line too long",
                "location": {"row": 1, "column": 1},
            },
            {
                "filename": os.path.join(p_dir, "foo.py"),
                "code": "E501",
                "message": "Line too long",
                "location": {"row": 2, "column": 1},
            },
        ]
        with open(p_json, "w") as f:
            json.dump(diag_p, f)

        new_diags = compare_ruff(b_json, p_json, b_dir, p_dir, {})
        self.assertEqual(len(new_diags), 1)
        self.assertEqual(new_diags[0]["location"]["row"], 2)

    def test_compare_ruff_renamed(self) -> None:
        b_dir = os.path.join(self.tmp_path, "b")
        p_dir = os.path.join(self.tmp_path, "p")
        os.makedirs(b_dir, exist_ok=True)
        os.makedirs(p_dir, exist_ok=True)

        diag = [
            {
                "filename": os.path.join(b_dir, "old_foo.py"),
                "code": "E501",
                "message": "Line too long",
                "location": {"row": 1, "column": 1},
            }
        ]
        b_json = os.path.join(self.tmp_path, "b.json")
        p_json = os.path.join(self.tmp_path, "p.json")
        with open(b_json, "w") as f:
            json.dump(diag, f)

        diag_p = [
            {
                "filename": os.path.join(p_dir, "new_foo.py"),
                "code": "E501",
                "message": "Line too long",
                "location": {"row": 1, "column": 1},
            }
        ]
        with open(p_json, "w") as f:
            json.dump(diag_p, f)

        rename_map = {"old_foo.py": "new_foo.py"}
        new_diags = compare_ruff(b_json, p_json, b_dir, p_dir, rename_map)
        self.assertEqual(len(new_diags), 0)

    def test_compare_pyright_error(self) -> None:
        b_dir = os.path.join(self.tmp_path, "b")
        p_dir = os.path.join(self.tmp_path, "p")
        os.makedirs(b_dir, exist_ok=True)
        os.makedirs(p_dir, exist_ok=True)

        b_json = os.path.join(self.tmp_path, "b.json")
        p_json = os.path.join(self.tmp_path, "p.json")
        with open(b_json, "w") as f:
            json.dump({"generalDiagnostics": []}, f)

        diag_p = {
            "generalDiagnostics": [
                {
                    "file": os.path.join(p_dir, "foo.py"),
                    "severity": "error",
                    "message": "Type mismatch",
                    "rule": "reportGeneralTypeIssues",
                }
            ]
        }
        with open(p_json, "w") as f:
            json.dump(diag_p, f)

        new_diags = compare_pyright(b_json, p_json, b_dir, p_dir, {})
        self.assertEqual(len(new_diags), 1)

    def test_compare_pyright_malformed_schema_raises(self) -> None:
        b_dir = os.path.join(self.tmp_path, "b")
        p_dir = os.path.join(self.tmp_path, "p")
        os.makedirs(b_dir, exist_ok=True)
        os.makedirs(p_dir, exist_ok=True)

        b_json = os.path.join(self.tmp_path, "b.json")
        p_json = os.path.join(self.tmp_path, "p.json")
        with open(b_json, "w") as f:
            json.dump({}, f)  # Missing generalDiagnostics key
        with open(p_json, "w") as f:
            json.dump({"generalDiagnostics": []}, f)

        with self.assertRaises(ValueError):
            compare_pyright(b_json, p_json, b_dir, p_dir, {})


if __name__ == "__main__":
    unittest.main()
