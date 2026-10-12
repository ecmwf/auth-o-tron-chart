"""Generate values.schema.json `config` from the Auth-O-Tron server JSON Schema.

The server publishes draft 2020-12; Helm 3.17 validates draft-07 only. The
conversion is mechanical and fails closed on keywords it does not understand:

* `$defs/X` moves to the chart root as `definitions/authotron.X`, and every
  `#/$defs/X` reference is rewritten to `#/definitions/authotron.X`.
* 2020-12 evaluates keywords next to `$ref`; draft-07 ignores them. A schema
  such as `{"$ref": "#/$defs/A", "required": ["type"]}` therefore becomes
  `{"allOf": [{"$ref": "#/definitions/authotron.A"}, {"required": ["type"]}]}`.
  A bare `{"$ref": ...}` is kept as is. Wrapping preserves sibling
  `additionalProperties: false`: it applies to the sibling's own (empty)
  `properties`, exactly as 2020-12 evaluates it beside `$ref`.
* `deprecated` (2019-09+) is copied as an annotation; draft-07 ignores unknown
  annotations, so it never affects validation.

The server schema is read from a commit, never from an uncommitted file:
* `--source-commit SHA` reads `git show SHA:authotron/schema.json` from the
  server repository containing --schema-path and requires it to be
  byte-identical to --schema-path.
* Without it, the checkout's HEAD is used and uncommitted schema edits are
  refused.

Chart-owned deltas (CHART_OVERRIDES) are applied afterwards and each one asserts
the exact server value it replaces, so a server change forces a review.

Usage:
  python3 tools/generate_config_schema.py --schema-path <server>/authotron/schema.json
  python3 tools/generate_config_schema.py --schema-path <server>/authotron/schema.json \
      --source-commit <full SHA>
  python3 tools/generate_config_schema.py --schema-path <pinned schema.json> --check
"""

import argparse
import copy
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

CHART = Path(__file__).resolve().parents[1]
VALUES_SCHEMA = CHART / "values.schema.json"
PREFIX = "authotron."
SOURCE_KEY = "x-authotron-source"
REPOSITORY = "ecmwf/auth-o-tron"
SOURCE_PATH = "authotron/schema.json"

# Keywords with identical draft-07 semantics. Anything else aborts generation.
KEYWORDS = {
    "$ref", "additionalProperties", "allOf", "anyOf", "const", "default",
    "deprecated", "description", "else", "enum", "examples", "exclusiveMaximum",
    "exclusiveMinimum", "format", "if", "items", "maxItems", "maxLength",
    "maxProperties", "maximum", "minItems", "minLength", "minProperties",
    "minimum", "multipleOf", "not", "oneOf", "pattern", "patternProperties",
    "properties", "propertyNames", "readOnly", "required", "then", "title",
    "type", "uniqueItems", "writeOnly",
}  # fmt: skip
SCHEMA_MAPS = {"properties", "patternProperties"}
SCHEMA_LISTS = {"allOf", "anyOf", "oneOf"}
SCHEMA_VALUES = {
    "items", "additionalProperties", "not", "if", "then", "else", "propertyNames",
}  # fmt: skip

VALKEY = ("definitions", PREFIX + "BrowserBackendConfig", "oneOf", 1)
# (path, expected server value, chart value, reason)
CHART_OVERRIDES = [
    (
        (*VALKEY, "required"),
        ["type", "url", "key_prefix", "password"],
        ["type"],
        "chart injects url (bundled) and key_prefix; password comes from a Secret env",
    ),
    (
        (*VALKEY, "properties", "password"),
        {"type": "string", "writeOnly": True},
        {"type": "string", "writeOnly": True, "maxLength": 0},
        "credentials never belong in values/ConfigMap",
    ),
    (
        (*VALKEY, "properties", "key_prefix"),
        {"type": "string"},
        {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "pattern": "^[A-Za-z0-9:_-]+$",
        },
        "chart-generated prefixes must stay within the documented safe alphabet",
    ),
]


def ref_target(ref):
    match = re.fullmatch(r"#/\$defs/([A-Za-z0-9_]+)", ref)
    if not match:
        raise SystemExit(f"unsupported $ref {ref!r}")
    return f"#/definitions/{PREFIX}{match.group(1)}"


def convert(node, where):
    if not isinstance(node, dict):
        raise SystemExit(f"{where}: expected a schema object")
    unknown = set(node) - KEYWORDS
    if unknown:
        raise SystemExit(f"{where}: unsupported keywords {sorted(unknown)}")
    out = {}
    for key, value in node.items():
        if key == "$ref":
            out[key] = ref_target(value)
        elif key in SCHEMA_MAPS:
            out[key] = {k: convert(v, f"{where}/{key}/{k}") for k, v in value.items()}
        elif key in SCHEMA_LISTS:
            out[key] = [convert(v, f"{where}/{key}/{i}") for i, v in enumerate(value)]
        elif key in SCHEMA_VALUES and isinstance(value, dict):
            out[key] = convert(value, f"{where}/{key}")
        else:
            out[key] = copy.deepcopy(value)
    if "$ref" in out and len(out) > 1:
        ref = {"$ref": out.pop("$ref")}
        out = {"allOf": [ref, out]}
    return out


def lookup(root, path):
    for part in path[:-1]:
        root = root[part]
    return root, path[-1]


def apply_overrides(root):
    for path, expected, value, reason in CHART_OVERRIDES:
        try:
            parent, key = lookup(root, path)
            actual = parent[key]
        except (KeyError, IndexError, TypeError):
            actual = None
        if actual != expected:
            raise SystemExit(
                f"server schema changed at {'/'.join(map(str, path))} "
                f"({reason}); review CHART_OVERRIDES.\n"
                f"expected: {json.dumps(expected)}\nactual:   {json.dumps(actual)}"
            )
        parent[key] = copy.deepcopy(value)


def git(schema_path, *args, text=True):
    """Run git in the repository containing `schema_path`."""
    directory = str(Path(schema_path).resolve().parent)
    try:
        return subprocess.run(
            ["git", "-C", directory, *args],
            check=True,
            capture_output=True,
            text=text,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"git {' '.join(args)} failed for {directory}") from error


def head_commit(schema_path):
    """HEAD of the schema's checkout; refuses uncommitted schema edits."""
    commit = git(schema_path, "rev-parse", "HEAD").strip()
    name = Path(schema_path).resolve().name
    if git(schema_path, "status", "--porcelain", "--", name).strip():
        raise SystemExit("server schema has uncommitted changes; commit them first")
    return commit


def require_committed(schema_path, commit, raw):
    """Fail unless `commit:authotron/schema.json` is byte-identical to `raw`."""
    committed = git(schema_path, "show", f"{commit}:{SOURCE_PATH}", text=False)
    if committed != raw:
        raise SystemExit(
            f"{schema_path} differs from {REPOSITORY}@{commit}:{SOURCE_PATH}; "
            "commit the schema or pass the commit that contains it"
        )


def generate(chart_schema, raw, commit):
    server = json.loads(raw)
    if not server.get("$schema", "").endswith("/2020-12/schema"):
        raise SystemExit("expected a draft 2020-12 server schema")
    body = {k: v for k, v in server.items() if k not in ("$schema", "$defs")}
    defs = {
        PREFIX + name: convert(schema, f"$defs/{name}")
        for name, schema in server["$defs"].items()
    }
    result = copy.deepcopy(chart_schema)
    chart_defs = {
        k: v
        for k, v in result.get("definitions", {}).items()
        if not k.startswith(PREFIX)
    }
    result["definitions"] = {**chart_defs, **defs}
    config = convert(body, "#")
    config[SOURCE_KEY] = {
        "repository": REPOSITORY,
        "commit": commit,
        "path": SOURCE_PATH,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    result["properties"]["config"] = config
    apply_overrides(result)
    return json.dumps(result, indent=2, ensure_ascii=False) + "\n"


def regenerate_hint(commit):
    return (
        f"values.schema.json does not match {REPOSITORY}@{commit}:{SOURCE_PATH}.\n"
        "Check out that server commit (or the intended new one) and run:\n"
        "  python3 tools/generate_config_schema.py "
        f"--schema-path <server checkout>/{SOURCE_PATH} --source-commit <full SHA>"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--schema-path", required=True, type=Path)
    parser.add_argument("--check", action="store_true", help="fail on drift")
    parser.add_argument("--source-commit", help="full server commit SHA")
    args = parser.parse_args(argv)
    current_text = VALUES_SCHEMA.read_text()
    current = json.loads(current_text)
    raw = args.schema_path.read_bytes()
    pinned = current["properties"]["config"].get(SOURCE_KEY, {})
    if args.check:
        commit = args.source_commit or pinned.get("commit", "")
    else:
        commit = args.source_commit or head_commit(args.schema_path)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        parser.error(f"source commit must be a full SHA, got {commit!r}")
    if not args.check:
        require_committed(args.schema_path, commit, raw)
    output = generate(current, raw, commit)
    if args.check:
        if output != current_text:
            print(regenerate_hint(commit), file=sys.stderr)
            return 1
        print(f"values.schema.json matches {REPOSITORY}@{commit[:12]}.")
        return 0
    VALUES_SCHEMA.write_text(output)
    print(f"wrote {VALUES_SCHEMA.relative_to(CHART)} from {REPOSITORY}@{commit[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
