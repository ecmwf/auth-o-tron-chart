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


LABEL_MATCHER_RE = re.compile(
    r'\s*([A-Za-z_][A-Za-z0-9_]*)\s*(=~|!~|!=|=)\s*("(?:\\.|[^"\\])*")\s*(?:,|$)'
)
NAME_REGEX_UNION_RE = re.compile(r'__name__\s*=~\s*"[^"]*\|[^"]*"')
REQUIRED_SCOPE_MATCHERS = {
    ("namespace", "=~", '"$namespace"'),
    ("job", "=~", '"$job"'),
}


def label_matchers(selector: str) -> tuple[tuple[str, str, str], ...]:
    matchers: list[tuple[str, str, str]] = []
    position = 0
    while position < len(selector):
        matcher = LABEL_MATCHER_RE.match(selector, position)
        if not matcher:
            raise ValueError(f"could not parse selector labels {selector!r}")
        matchers.append((matcher.group(1), matcher.group(2), matcher.group(3)))
        position = matcher.end()
    return tuple(sorted(matchers))


def fallback_pattern(new_name: str, legacy_name: str) -> re.Pattern[str]:
    return re.compile(
        rf"""
        rate\(\s*{re.escape(new_name)}
        \{{(?P<new_labels>[^{{}}]*)\}}
        \[(?P<new_range>[^\[\]]+)\]\s*\)
        \s+or\s+
        rate\(\s*{re.escape(legacy_name)}
        \{{(?P<legacy_labels>[^{{}}]*)\}}
        \[(?P<legacy_range>[^\[\]]+)\]\s*\)
        """,
        re.VERBOSE,
    )


def validate_fallback(
    path: str,
    expression: str,
    new_name: str,
    legacy_name: str,
    match: re.Match[str],
    errors: list[str],
) -> None:
    try:
        new_labels = label_matchers(match.group("new_labels"))
        legacy_labels = label_matchers(match.group("legacy_labels"))
    except ValueError as error:
        errors.append(f"{path}: {error}")
        return

    if new_labels != legacy_labels:
        errors.append(
            f"{path}: {new_name} and {legacy_name} fallback selectors have "
            "different labels"
        )
    if not REQUIRED_SCOPE_MATCHERS.issubset(new_labels):
        errors.append(
            f"{path}: {new_name} fallback must retain the namespace and job labels"
        )
    if match.group("new_range").strip() != match.group("legacy_range").strip():
        errors.append(f"{path}: {new_name} and {legacy_name} use different ranges")

    aggregation = re.search(
        r"sum(?:\s+by\s*\((?P<grouping>[^)]*)\))?\s*\(\s*$",
        expression[: match.start()],
    )
    if not aggregation or not re.match(r"\s*\)", expression[match.end() :]):
        errors.append(
            f"{path}: {new_name} or {legacy_name} must be the direct operand of "
            "an enclosing sum"
        )
        return

    if new_name.endswith("_bucket"):
        grouping = aggregation.group("grouping")
        grouping_labels = (
            {label.strip() for label in grouping.split(",")} if grouping else set()
        )
        if "le" not in grouping_labels:
            errors.append(
                f"{path}: histogram fallback for {new_name} must be summed by le"
            )


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
        if NAME_REGEX_UNION_RE.search(expression):
            errors.append(
                f"{path}: __name__ regex unions are not valid migration fallbacks"
            )

        for new_name, legacy_name in METRIC_RENAMES:
            matches = list(fallback_pattern(new_name, legacy_name).finditer(expression))
            seen[(new_name, legacy_name)] += len(matches)
            for match in matches:
                validate_fallback(
                    path, expression, new_name, legacy_name, match, errors
                )

            for metric in (new_name, legacy_name):
                metric_pattern = re.compile(
                    rf"(?<![A-Za-z0-9_:]){re.escape(metric)}(?![A-Za-z0-9_:])"
                )
                for metric_match in metric_pattern.finditer(expression):
                    if not any(
                        match.start() <= metric_match.start() < match.end()
                        for match in matches
                    ):
                        errors.append(
                            f"{path}: {metric} must be used in a new-first, "
                            "label-matched rate(new) or rate(legacy) fallback"
                        )

    if require_fallbacks:
        for pair, count in seen.items():
            if count == 0:
                errors.append(
                    f"missing migration fallback for {pair[0]} or {pair[1]} while "
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
