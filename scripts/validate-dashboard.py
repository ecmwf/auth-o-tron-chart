#!/usr/bin/env python3
"""Validate the Grafana dashboard and its metric-name migration contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterator

LEGACY_DEFAULT_VERSION = "0.3.6"
METRIC_RENAMES = (
    ("authotron_auth_requests_total", "auth_requests_total"),
    ("authotron_auth_duration_seconds_bucket", "auth_duration_seconds_bucket"),
    ("authotron_auth_provider_attempts_total", "auth_provider_attempts_total"),
    (
        "authotron_auth_provider_duration_seconds_bucket",
        "auth_provider_duration_seconds_bucket",
    ),
    ("authotron_augmenter_attempts_total", "augmenter_attempts_total"),
    (
        "authotron_augmenter_duration_seconds_bucket",
        "augmenter_duration_seconds_bucket",
    ),
)


def expressions(value: Any, path: str = "dashboard") -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key == "expr" and isinstance(child, str):
                yield child_path, child
            else:
                yield from expressions(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from expressions(child, f"{path}[{index}]")


def scalar(path: Path, key: str) -> str:
    match = re.search(
        rf"(?m)^{re.escape(key)}:\s*[\"']?([^\s#\"']+)",
        path.read_text(encoding="utf-8"),
    )
    if not match:
        raise ValueError(f"could not find {key!r} in {path}")
    return match.group(1)


def image_tag(path: Path) -> str:
    in_image = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == "image:":
            in_image = True
        elif in_image and line.startswith("  tag:"):
            return line.split(":", 1)[1].split("#", 1)[0].strip().strip("\"'")
        elif in_image and line and not line.startswith(("  ", "#")):
            break
    raise ValueError(f"could not find image.tag in {path}")


def validate_migration(
    query_expressions: list[tuple[str, str]], chart: Path, values: Path
) -> None:
    app_version = scalar(chart, "appVersion")
    default_image = image_tag(values)
    if app_version != default_image:
        raise ValueError(
            f"Chart appVersion ({app_version}) and values image.tag ({default_image}) differ"
        )

    require_fallbacks = app_version == LEGACY_DEFAULT_VERSION
    seen: dict[tuple[str, str], int] = {pair: 0 for pair in METRIC_RENAMES}
    errors: list[str] = []

    for path, expression in query_expressions:
        for new_name, legacy_name in METRIC_RENAMES:
            selector = f'{{__name__=~"{new_name}|{legacy_name}"'
            seen[(new_name, legacy_name)] += expression.count(selector)
            remainder = expression.replace(selector, "")
            for metric in (new_name, legacy_name):
                if re.search(
                    rf"(?<![A-Za-z0-9_:]){re.escape(metric)}(?![A-Za-z0-9_:])",
                    remainder,
                ):
                    errors.append(
                        f"{path}: {metric} is used outside its new-or-legacy selector"
                    )

    if require_fallbacks:
        for pair, count in seen.items():
            if count == 0:
                errors.append(
                    f"missing migration selector for {pair[0]}|{pair[1]} while "
                    f"the chart defaults to {LEGACY_DEFAULT_VERSION}"
                )
    if errors:
        raise ValueError("\n".join(errors))


def parse_promql(query_expressions: list[tuple[str, str]], promtool: Path) -> None:
    substitutions = {
        "$__rate_interval": "5m",
        "$namespace": ".+",
        "$job": ".+",
    }
    errors: list[str] = []
    for path, expression in query_expressions:
        parsed_expression = expression
        for variable, replacement in substitutions.items():
            parsed_expression = parsed_expression.replace(variable, replacement)
        if "$" in parsed_expression:
            errors.append(f"{path}: unsupported Grafana variable in {expression!r}")
            continue
        result = subprocess.run(
            [str(promtool), "--experimental", "promql", "format", parsed_expression],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode:
            errors.append(f"{path}: {result.stderr.strip()}")
    if errors:
        raise ValueError("\n".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dashboard", type=Path)
    parser.add_argument("--chart", type=Path, default=Path("Chart.yaml"))
    parser.add_argument("--values", type=Path, default=Path("values.yaml"))
    parser.add_argument("--promtool", type=Path)
    args = parser.parse_args()

    try:
        dashboard = json.loads(args.dashboard.read_text(encoding="utf-8"))
        query_expressions = list(expressions(dashboard))
        if not query_expressions:
            raise ValueError("dashboard contains no PromQL expressions")
        validate_migration(query_expressions, args.chart, args.values)
        if args.promtool:
            parse_promql(query_expressions, args.promtool.resolve())
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"dashboard validation failed: {error}", file=sys.stderr)
        return 1

    parser_status = " and parsed as PromQL" if args.promtool else ""
    print(
        f"validated {args.dashboard}: {len(query_expressions)} expressions{parser_status}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
