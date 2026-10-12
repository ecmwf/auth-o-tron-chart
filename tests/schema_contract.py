"""Extract/verify the versioned browser numeric contract, without network access."""

import argparse
import hashlib
import json
from pathlib import Path
import re

CHART = Path(__file__).resolve().parents[1]
FIXTURE = CHART / "tests/application-contract.json"


def load_contract():
    return json.loads(FIXTURE.read_text())


def numeric_properties(properties):
    return {
        name: {key: prop[key] for key in ("type", "minimum", "maximum")}
        for name, prop in properties.items()
        if "minimum" in prop and "maximum" in prop
    }


def valkey_properties(schema):
    return next(
        variant["properties"]
        for variant in schema["oneOf"]
        if variant["properties"]["type"]["const"] == "valkey"
    )


def extract(schema):
    session = schema["$defs"]["BrowserSessionConfig"]["properties"]
    backend = valkey_properties(schema["$defs"]["BrowserBackendConfig"])
    return {
        "session": numeric_properties(session),
        "backend": numeric_properties(backend),
        "default_max_inflight_logins": session["max_inflight_logins"]["default"],
    }


def verify_chart(contract):
    schema = json.loads((CHART / "values.schema.json").read_text())
    session = schema["properties"]["config"]["properties"]["ui"]["properties"][
        "browser_session"
    ]["properties"]
    assert numeric_properties(session) == contract["session"], "session bounds drift"
    assert (
        numeric_properties(valkey_properties(session["backend"])) == contract["backend"]
    ), "backend bounds drift"
    target = schema["properties"]["autoscaling"]["properties"]["targetInFlightLogins"]
    for key in ("minimum", "maximum"):
        assert target[key] == contract["session"]["max_inflight_logins"][key]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema-path", required=True, type=Path)
    parser.add_argument("--generate", action="store_true", help="print fixture JSON")
    parser.add_argument("--source-commit", help="full server commit for generation")
    parser.add_argument("--require-source-hash", action="store_true")
    args = parser.parse_args()
    raw = args.schema_path.read_bytes()
    contract = extract(json.loads(raw))
    digest = hashlib.sha256(raw).hexdigest()
    if args.generate:
        if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit or ""):
            parser.error("--generate requires --source-commit with a full commit SHA")
        print(
            json.dumps(
                {
                    "source": {
                        "repository": "ecmwf/auth-o-tron",
                        "commit": args.source_commit,
                        "path": "authotron/schema.json",
                        "sha256": digest,
                    },
                    "contract": contract,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    fixture = load_contract()
    if args.require_source_hash:
        assert digest == fixture["source"]["sha256"], "pinned source hash mismatch"
    assert contract == fixture["contract"], (
        "application contract drift; regenerate and review"
    )
    verify_chart(contract)
    count = len(contract["session"]) + len(contract["backend"])
    print(f"Application schema parity passed ({count} bounds and in-flight default).")


if __name__ == "__main__":
    main()
