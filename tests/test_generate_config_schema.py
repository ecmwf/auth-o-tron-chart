"""Self-tests for tools/generate_config_schema.py. Run: python3 tests/<this file>."""

import importlib.util
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOL = Path(__file__).resolve().parents[1] / "tools" / "generate_config_schema.py"
spec = importlib.util.spec_from_file_location("generate_config_schema", TOOL)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


class ServerRepo:
    """Throwaway git repository holding authotron/schema.json."""

    def __init__(self, tmp):
        self.root = Path(tmp)
        self.schema = self.root / gen.SOURCE_PATH
        self.schema.parent.mkdir(parents=True)
        self.run("init", "-q")

    def run(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            capture_output=True,
            text=True,
            env=GIT_ENV,
        ).stdout.strip()

    def commit(self, content):
        self.schema.write_bytes(content)
        self.run("add", gen.SOURCE_PATH)
        self.run("commit", "-q", "-m", "schema")
        return self.run("rev-parse", "HEAD")


class SourceCommitTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="authotron-gen-")
        self.addCleanup(tmp.cleanup)
        self.repo = ServerRepo(tmp.name)
        self.commit = self.repo.commit(b'{"a": 1}\n')

    def test_matching_bytes_accepted(self):
        gen.require_committed(self.repo.schema, self.commit, b'{"a": 1}\n')

    def test_commit_bytes_mismatch_rejected(self):
        with self.assertRaisesRegex(SystemExit, "differs from"):
            gen.require_committed(self.repo.schema, self.commit, b'{"a": 2}\n')

    def test_write_mode_rejects_mismatch_before_writing(self):
        self.repo.schema.write_bytes(b'{"a": 2}\n')
        with tempfile.TemporaryDirectory() as out:
            target = Path(out) / "values.schema.json"
            target.write_text(gen.VALUES_SCHEMA.read_text())
            before = target.read_text()
            with mock.patch.object(gen, "VALUES_SCHEMA", target):
                with self.assertRaisesRegex(SystemExit, "differs from"):
                    gen.main(
                        [
                            "--schema-path",
                            str(self.repo.schema),
                            "--source-commit",
                            self.commit,
                        ]
                    )
            self.assertEqual(target.read_text(), before)

    def test_head_refuses_uncommitted_edits(self):
        self.assertEqual(gen.head_commit(self.repo.schema), self.commit)
        self.repo.schema.write_bytes(b'{"a": 2}\n')
        with self.assertRaisesRegex(SystemExit, "uncommitted"):
            gen.head_commit(self.repo.schema)

    def test_check_hint_names_pin_and_command(self):
        hint = gen.regenerate_hint("f" * 40)
        self.assertIn(f"{gen.REPOSITORY}@{'f' * 40}:{gen.SOURCE_PATH}", hint)
        self.assertIn("--source-commit", hint)
        self.assertNotIn("../", hint)


class ConvertTests(unittest.TestCase):
    def test_ref_beside_additional_properties_false_is_wrapped(self):
        schema = {
            "$ref": "#/$defs/A",
            "additionalProperties": False,
            "required": ["type"],
        }
        self.assertEqual(
            gen.convert(schema, "#"),
            {
                "allOf": [
                    {"$ref": "#/definitions/authotron.A"},
                    {"additionalProperties": False, "required": ["type"]},
                ]
            },
        )

    def test_bare_ref_is_kept(self):
        self.assertEqual(
            gen.convert({"$ref": "#/$defs/A"}, "#"),
            {"$ref": "#/definitions/authotron.A"},
        )

    def test_unknown_keyword_fails_closed(self):
        for keyword in ["unevaluatedProperties", "dependentRequired", "$anchor"]:
            with self.subTest(keyword=keyword):
                with self.assertRaisesRegex(SystemExit, re.escape(keyword)):
                    gen.convert({"type": "object", keyword: {}}, "#")
        with self.assertRaisesRegex(SystemExit, "unsupported \\$ref"):
            gen.convert({"$ref": "https://example.test/x"}, "#")

    def test_deprecated_is_a_copied_annotation(self):
        # draft-07 ignores `deprecated`; it documents, never validates.
        schema = {"type": "string", "deprecated": True}
        self.assertEqual(gen.convert(schema, "#"), schema)


if __name__ == "__main__":
    unittest.main(verbosity=2)
