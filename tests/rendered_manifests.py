#!/usr/bin/env python3
"""Rendered-manifest assertions for the Auth-O-Tron 0.4 chart contract."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
RELEASE_ARGS = [
    "helm",
    "template",
    "auth-o-tron",
    str(ROOT),
    "--namespace",
    "auth-o-tron",
]
REQUIRED_VALUES = [
    "--set-string",
    "config.jwt.iss=https://auth.example.com,config.jwt.kid=key-2026-01",
]


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*RELEASE_ARGS, *args],
        check=False,
        text=True,
        capture_output=True,
    )


def render(*args: str) -> str:
    result = run(*REQUIRED_VALUES, *args)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout


def document(manifest: str, kind: str) -> str:
    matches = [
        part
        for part in manifest.split("\n---")
        if f"\nkind: {kind}\n" in f"\n{part}\n"
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one {kind}, found {len(matches)}")
    return matches[0]


def assert_line(text: str, line: str) -> None:
    if line not in text.splitlines():
        raise AssertionError(f"missing line {line!r}")


def config_checksum(manifest: str) -> str:
    deployment = document(manifest, "Deployment")
    prefix = "        checksum/config: "
    matches = [line for line in deployment.splitlines() if line.startswith(prefix)]
    if len(matches) != 1:
        raise AssertionError(f"expected one config checksum, found {len(matches)}")
    return matches[0].removeprefix(prefix)


def assert_rejected(message: str, *args: str) -> None:
    result = run(*args)
    if result.returncode == 0:
        raise AssertionError(f"expected rendering to reject {args!r}")
    if message not in result.stderr:
        raise AssertionError(f"expected {message!r} in:\n{result.stderr}")


def test_defaults() -> None:
    manifest = render()
    configmap = document(manifest, "ConfigMap")
    deployment = document(manifest, "Deployment")

    assert_line(configmap, "      iss: https://auth.example.com")
    assert_line(configmap, "      aud: polytope-server")
    assert_line(configmap, "      kid: key-2026-01")
    assert_line(configmap, "      exp: 3600")
    for forbidden in ("private_key", "secret:", "PRIVATE KEY", "AOT_JWT__PRIVATE_KEY"):
        if forbidden in configmap:
            raise AssertionError(f"ConfigMap contains forbidden value {forbidden!r}")

    assert_line(deployment, '          image: "eccr.ecmwf.int/auth-o-tron/auth-o-tron:0.4.0"')
    assert_line(deployment, "            - name: AOT_JWT__PRIVATE_KEY")
    assert_line(deployment, "                  name: auth-o-tron-jwt")
    assert_line(deployment, "                  key: private-key.pem")
    if "\nkind: Secret\n" in f"\n{manifest}\n":
        raise AssertionError("the chart must reference, not create, the signing Secret")


def test_secret_reference_override() -> None:
    manifest = render(
        "--set-string",
        "jwt.privateKeySecret.name=auth-o-tron-jwt-key-2026-02,"
        "jwt.privateKeySecret.key=signing.pem",
    )
    deployment = document(manifest, "Deployment")
    assert_line(deployment, "                  name: auth-o-tron-jwt-key-2026-02")
    assert_line(deployment, "                  key: signing.pem")


def test_rotation_values_trigger_rollout() -> None:
    original = config_checksum(render())
    new_kid = config_checksum(
        render("--set-string", "config.jwt.kid=key-2026-02")
    )
    new_secret = config_checksum(
        render(
            "--set-string",
            "jwt.privateKeySecret.name=auth-o-tron-jwt-key-2026-02",
        )
    )
    if len({original, new_kid, new_secret}) != 3:
        raise AssertionError("kid and Secret reference changes must alter pod checksum")


def test_required_and_private_key_guards() -> None:
    assert_rejected(
        "config.jwt.iss is required",
        "--set-string",
        "config.jwt.kid=key-2026-01",
    )
    assert_rejected(
        "config.jwt.kid is required",
        "--set-string",
        "config.jwt.iss=https://auth.example.com",
    )
    assert_rejected(
        "config.jwt.aud is required",
        *REQUIRED_VALUES,
        "--set-string",
        "config.jwt.aud=",
    )
    assert_rejected(
        "jwt.privateKeySecret.name is required",
        *REQUIRED_VALUES,
        "--set-string",
        "jwt.privateKeySecret.name=",
    )
    assert_rejected(
        "jwt.privateKeySecret.key is required",
        *REQUIRED_VALUES,
        "--set-string",
        "jwt.privateKeySecret.key=",
    )
    assert_rejected(
        "config.jwt.secret was removed",
        *REQUIRED_VALUES,
        "--set-string",
        "config.jwt.secret=legacy",
    )
    assert_rejected(
        "config.jwt.private_key must not be stored",
        *REQUIRED_VALUES,
        "--set-string",
        "config.jwt.private_key=PEM_LEAK",
    )
    assert_rejected(
        "extraEnv must not define AOT_JWT__PRIVATE_KEY",
        *REQUIRED_VALUES,
        "--set-string",
        "extraEnv[0].name=AOT_JWT__PRIVATE_KEY,extraEnv[0].value=PEM_LEAK",
    )


if __name__ == "__main__":
    test_defaults()
    test_secret_reference_override()
    test_rotation_values_trigger_rollout()
    test_required_and_private_key_guards()
    print("rendered manifest assertions passed")
