"""Offline render contracts. Run: python3 tests/render_contract.py (Helm + PyYAML)."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

CHART = Path(__file__).resolve().parents[1]
PASSWORD_ENV = "AOT_UI__BROWSER_SESSION__BACKEND__PASSWORD"
HOMES = {
    "HELM_CACHE_HOME": "/tmp/opencode/authotron-valkey-helm-cache",
    "HELM_CONFIG_HOME": "/tmp/opencode/authotron-valkey-helm-config",
    "HELM_DATA_HOME": "/tmp/opencode/authotron-valkey-helm-data",
}
BUNDLED = {
    "valkey": {"enabled": True, "auth": {"usersExistingSecret": "browser-secret"}},
    "browserState": {"passwordSecret": {"name": "browser-secret", "key": "default"}},
}
DIRECT = {
    "enabled": True,
    "basic": {"provider_name": "basic-provider"},
    "browser_session": {
        "public_origin": "https://login.example.test",
        "session_ttl_seconds": 600,
        "transaction_ttl_seconds": 120,
        "backend": {
            "type": "valkey",
            "connect_timeout_ms": 2000,
            "operation_timeout_ms": 1000,
        },
    },
}


def render(values=None, release="aot", chart=CHART, failed=False, namespace="contract"):
    result = subprocess.run(
        ["helm", "template", release, str(chart), "--namespace", namespace, "-f", "-"],
        input=yaml.safe_dump(values or {}),
        text=True,
        capture_output=True,
        env={**os.environ, **HOMES},
    )
    if failed:
        assert result.returncode, "render unexpectedly succeeded"
        return result.stdout + result.stderr
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def config(docs):
    return next(
        yaml.safe_load(d["data"]["config.yaml"])
        for d in docs
        if d["kind"] == "ConfigMap" and "config.yaml" in d["data"]
    )


def app(docs):
    return next(
        d
        for d in docs
        if d["kind"] == "Deployment"
        and d["spec"]["template"]["spec"]["containers"][0]["name"]
        == "auth-o-tron-chart"
    )


class Contracts(unittest.TestCase):
    def test_default_disabled_and_preview(self):
        default = render()
        self.assertEqual(len(default), 4)
        self.assertEqual(default, render({"valkey": {"enabled": False}}))
        self.assertEqual(default, render({"autoscaling": {"enabled": False}}))
        self.assertEqual(config(default)["ui"], {})
        preview = render(
            {"config": {"ui": {"enabled": True}}, "ingress": {"enabled": True}}
        )
        self.assertEqual(len(preview), 5)
        self.assertNotIn("browser_session", config(preview)["ui"])

    def test_api_only_bundled_does_not_enable_ui(self):
        docs = render(BUNDLED)
        self.assertEqual(config(docs)["ui"], {})
        self.assertFalse(
            any(
                d["kind"]
                in ("Ingress", "PersistentVolumeClaim", "StatefulSet", "Secret")
                for d in docs
            )
        )

    def test_direct_bundled_naming_and_policy(self):
        for release, overrides in [
            ("aot", {}),
            ("aot-valkey", {}),
            ("my-auth-o-tron", {}),
            ("aot", {"nameOverride": "state"}),
            ("aot", {"fullnameOverride": "shared-browser"}),
            ("aot", {"fullnameOverride": "s" * 58}),
        ]:
            with self.subTest(release=release, overrides=overrides):
                values = copy.deepcopy(BUNDLED)
                values["valkey"].update(overrides)
                values["config"] = {"ui": copy.deepcopy(DIRECT)}
                # Bundled helper must replace a stale supplied URL.
                values["config"]["ui"]["browser_session"]["backend"]["url"] = (
                    "redis://stale:6379/0"
                )
                values["replicaCount"] = 2
                docs = render(values, release)
                primary = next(
                    d
                    for d in docs
                    if d["kind"] == "Service"
                    and d["metadata"]
                    .get("labels", {})
                    .get("app.kubernetes.io/component")
                    == "primary"
                )
                backend = config(docs)["ui"]["browser_session"]["backend"]
                self.assertEqual(
                    backend["url"], f"redis://{primary['metadata']['name']}:6379/0"
                )
                self.assertRegex(
                    backend["key_prefix"], r"^authotron:browser:v1:[0-9a-f]{32}$"
                )
                self.assertEqual(
                    config(docs)["ui"]["browser_session"]["session_ttl_seconds"], 600
                )
                pod = app(docs)["spec"]["template"]
                credential = pod["spec"]["containers"][0]["env"][0]
                self.assertEqual(
                    credential,
                    {
                        "name": PASSWORD_ENV,
                        "valueFrom": {
                            "secretKeyRef": {"name": "browser-secret", "key": "default"}
                        },
                    },
                )
                policy = next(d for d in docs if d["kind"] == "NetworkPolicy")["spec"]
                peer = policy["ingress"][0]["from"]
                self.assertEqual(
                    peer, [{"podSelector": {"matchLabels": pod["metadata"]["labels"]}}]
                )
                self.assertEqual(
                    policy["podSelector"]["matchLabels"], primary["spec"]["selector"]
                )
                valkey = next(
                    d for d in docs if d["kind"] == "Deployment" and d != app(docs)
                )
                spec = valkey["spec"]["template"]["spec"]
                self.assertEqual(valkey["spec"]["strategy"]["type"], "Recreate")
                self.assertEqual(
                    spec["containers"][0]["image"], "docker.io/valkey/valkey:9.1.2"
                )
                self.assertEqual(spec["containers"][0]["command"], ["valkey-server"])
                self.assertEqual(
                    spec["containers"][0]["resources"]["limits"]["memory"], "256Mi"
                )
                self.assertIn({"name": "valkey-data", "emptyDir": {}}, spec["volumes"])
                self.assertIn(
                    {
                        "name": "valkey-users-secret",
                        "secret": {"secretName": "browser-secret", "defaultMode": 256},
                    },
                    spec["volumes"],
                )
                self.assertLessEqual(len(spec["initContainers"][0]["name"]), 63)
        for override in ["s" * 59, "state-" + "x" * 70]:
            values = copy.deepcopy(BUNDLED)
            values["valkey"]["fullnameOverride"] = override
            self.assertIn("fullname must be at most 58", render(values, failed=True))
        values = copy.deepcopy(BUNDLED)
        values["valkey"]["nameOverride"] = "s" * 55
        self.assertIn("fullname must be at most 58", render(values, failed=True))

    def test_external_and_memory(self):
        ui = copy.deepcopy(DIRECT)
        ui["browser_session"]["backend"]["url"] = "rediss://primary.example.test:6379/0"
        values = {
            "config": {"ui": ui},
            "browserState": BUNDLED["browserState"],
            "replicaCount": 2,
        }
        docs = render(values)
        self.assertEqual(len(docs), 4)
        self.assertEqual(
            config(docs)["ui"]["browser_session"]["backend"]["url"],
            ui["browser_session"]["backend"]["url"],
        )
        prefix = config(docs)["ui"]["browser_session"]["backend"]["key_prefix"]
        isolated = config(render(values, namespace="other"))["ui"]["browser_session"][
            "backend"
        ]["key_prefix"]
        self.assertNotEqual(prefix, isolated)
        changed = copy.deepcopy(values)
        changed["replicaCount"] = 3
        changed["config"]["ui"]["browser_session"]["session_ttl_seconds"] = 900
        self.assertEqual(
            prefix,
            config(render(changed))["ui"]["browser_session"]["backend"]["key_prefix"],
        )
        # Identity inputs may be long; the serialized prefix remains fixed length.
        changed["fullnameOverride"] = "f" * 63
        longest = config(render(changed, release="r" * 53, namespace="n" * 63))["ui"][
            "browser_session"
        ]["backend"]["key_prefix"]
        self.assertRegex(longest, r"^authotron:browser:v1:[0-9a-f]{32}$")
        self.assertEqual(len(longest), 53)
        changed["config"]["ui"]["browser_session"]["backend"]["key_prefix"] = (
            "operator_choice:shared"
        )
        self.assertEqual(
            config(render(changed))["ui"]["browser_session"]["backend"]["key_prefix"],
            "operator_choice:shared",
        )
        ui["browser_session"]["backend"] = {"type": "memory"}
        values.pop("browserState")
        self.assertIn("memory browser sessions require", render(values, failed=True))
        values["replicaCount"] = 1
        self.assertEqual(
            config(render(values))["ui"]["browser_session"]["backend"],
            {"type": "memory"},
        )

    def test_custom_secret_key_and_empty_password_placeholder(self):
        values = copy.deepcopy(BUNDLED)
        values["browserState"]["passwordSecret"]["key"] = "browser-password"
        values["valkey"]["auth"]["aclUsers"] = {
            "default": {"passwordKey": "browser-password"}
        }
        values["config"] = {"ui": copy.deepcopy(DIRECT)}
        values["config"]["ui"]["browser_session"]["backend"]["password"] = ""
        docs = render(values)
        env = app(docs)["spec"]["template"]["spec"]["containers"][0]["env"]
        self.assertEqual(env[0]["valueFrom"]["secretKeyRef"]["key"], "browser-password")
        script = next(
            d["data"]["init.sh"]
            for d in docs
            if d["kind"] == "ConfigMap" and "init.sh" in d["data"]
        )
        self.assertIn('get_user_password "default" "browser-password"', script)
        values["browserState"]["passwordSecret"]["key"] = "wrong-key"
        self.assertIn("must match bundled Valkey", render(values, failed=True))

    def test_strict_lint_profiles(self):
        bundled = copy.deepcopy(BUNDLED)
        bundled["config"] = {"ui": copy.deepcopy(DIRECT)}
        external = copy.deepcopy(bundled)
        external["valkey"] = {"enabled": False}
        external["config"]["ui"]["browser_session"]["backend"]["url"] = (
            "redis://primary.internal:6379/0"
        )
        cpu_hpa = {
            "autoscaling": {"enabled": True},
            "resources": {"requests": {"cpu": "100m"}},
        }
        custom_hpa = copy.deepcopy(bundled)
        custom_hpa["config"]["ui"]["browser_session"]["max_inflight_logins"] = 64
        custom_hpa["autoscaling"] = {
            "enabled": True,
            "targetCPUUtilizationPercentage": None,
            "targetInFlightLogins": 32,
        }
        for values in [{}, bundled, external, cpu_hpa, custom_hpa]:
            result = subprocess.run(
                ["helm", "lint", "--strict", str(CHART), "-f", "-"],
                input=yaml.safe_dump(values),
                text=True,
                capture_output=True,
                env={**os.environ, **HOMES},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_hpa_targets_and_ownership(self):
        values = {
            "autoscaling": {"enabled": True},
            "resources": {"requests": {"cpu": "250m", "memory": "128Mi"}},
            "replicaCount": 7,
        }
        for overrides in [
            {},
            {"nameOverride": "gateway"},
            {"fullnameOverride": "custom"},
        ]:
            docs = render({**values, **overrides})
            deployment = app(docs)
            self.assertNotIn("replicas", deployment["spec"])
            self.assertEqual(
                deployment["spec"]["template"]["spec"]["containers"][0]["resources"],
                values["resources"],
            )
            hpa = next(d for d in docs if d["kind"] == "HorizontalPodAutoscaler")
            self.assertEqual(hpa["apiVersion"], "autoscaling/v2")
            self.assertEqual(hpa["metadata"]["namespace"], "contract")
            self.assertEqual(hpa["metadata"]["name"], deployment["metadata"]["name"])
            self.assertEqual(
                hpa["spec"]["scaleTargetRef"],
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "name": deployment["metadata"]["name"],
                },
            )
            self.assertEqual(hpa["spec"]["minReplicas"], 2)
            self.assertEqual(hpa["spec"]["maxReplicas"], 10)
            self.assertEqual(
                hpa["spec"]["metrics"],
                [
                    {
                        "type": "Resource",
                        "resource": {
                            "name": "cpu",
                            "target": {"type": "Utilization", "averageUtilization": 70},
                        },
                    }
                ],
            )
            self.assertEqual(config(docs)["ui"], {})
        values.update(copy.deepcopy(BUNDLED))
        values["config"] = {"ui": copy.deepcopy(DIRECT)}
        values["config"]["ui"]["browser_session"]["max_inflight_logins"] = 64
        values["autoscaling"]["targetInFlightLogins"] = 32
        both = render(values)
        metrics = next(d for d in both if d["kind"] == "HorizontalPodAutoscaler")[
            "spec"
        ]["metrics"]
        self.assertEqual(len(metrics), 2)
        expected_pods = {
            "type": "Pods",
            "pods": {
                "metric": {"name": "authotron_browser_logins_inflight"},
                "target": {"type": "AverageValue", "averageValue": "32"},
            },
        }
        self.assertEqual(metrics[1], expected_pods)
        values["autoscaling"]["targetCPUUtilizationPercentage"] = None
        values.pop("resources")
        only = render(values)
        self.assertEqual(
            next(d for d in only if d["kind"] == "HorizontalPodAutoscaler")["spec"][
                "metrics"
            ],
            [expected_pods],
        )
        # Prometheus scraping may be managed externally instead of ServiceMonitor.
        values["metrics"] = {"serviceMonitor": {"enabled": False}}
        render(values)

    def test_hpa_rejections_and_memory(self):
        for cpu in [None, "", "0", "0m", "0.0", "-1", "invalid"]:
            values = {
                "autoscaling": {"enabled": True},
                "resources": {"requests": {"cpu": cpu}},
            }
            error = render(values, failed=True)
            self.assertIn(
                "/resources/requests/cpu" if cpu is None else "resources.requests.cpu",
                error,
            )
        for cpu in ["100m", "0.25", 1]:
            render(
                {
                    "autoscaling": {"enabled": True},
                    "resources": {"requests": {"cpu": cpu}},
                    "metrics": {"enabled": False},
                    "config": {"metrics": {"enabled": False}},
                }
            )
        custom = copy.deepcopy(BUNDLED)
        custom["config"] = {"ui": copy.deepcopy(DIRECT)}
        custom["autoscaling"] = {
            "enabled": True,
            "targetCPUUtilizationPercentage": None,
            "targetInFlightLogins": 4,
        }
        render(custom)  # Positive target below the implicit per-pod default of 8.
        absent = copy.deepcopy(custom)
        absent["config"].pop("ui")
        self.assertIn(
            "configured ui.basic or ui.ecmwf_api_key", render(absent, failed=True)
        )
        for inactive in [
            {},
            {"enabled": True},
            {
                "enabled": True,
                "sign_in_actions": [{"label": "SSO", "start_url": "/oauth2/start"}],
            },
            {**copy.deepcopy(DIRECT), "enabled": False},
        ]:
            values = copy.deepcopy(custom)
            values["config"]["ui"] = inactive
            self.assertIn(
                "configured ui.basic or ui.ecmwf_api_key", render(values, failed=True)
            )
        for cap, target in [(None, 8), (None, 9), (1, 1), (4, 4), (4, 5)]:
            values = copy.deepcopy(custom)
            values["autoscaling"]["targetInFlightLogins"] = target
            if cap is not None:
                values["config"]["ui"]["browser_session"]["max_inflight_logins"] = cap
            self.assertIn("strictly below effective", render(values, failed=True))
        ecmwf = copy.deepcopy(custom)
        ecmwf["config"]["ui"]["ecmwf_api_key"] = ecmwf["config"]["ui"].pop("basic")
        render(ecmwf)
        for override in [
            {"metrics": {"enabled": False}},
            {"config": {"metrics": {"enabled": False}}},
            {"config": {"metrics": {"port": 9091}}},
        ]:
            values = copy.deepcopy(custom)
            for key, value in override.items():
                if key == "config":
                    values["config"].update(value)
                else:
                    values[key] = value
            self.assertIn(
                "in-flight login autoscaling requires",
                render(values, failed=True),
            )
        for override in [
            {"minReplicas": 0},
            {"maxReplicas": 0},
            {"minReplicas": 11, "maxReplicas": 10},
            {"targetCPUUtilizationPercentage": 0},
            {"targetCPUUtilizationPercentage": 101},
            {"targetInFlightLogins": 0},
            {"targetInFlightLogins": 257},
            {"targetCPUUtilizationPercentage": None, "targetInFlightLogins": None},
        ]:
            values = {
                "autoscaling": {"enabled": True, **override},
                "resources": {"requests": {"cpu": "100m"}},
            }
            render(values, failed=True)
        values = copy.deepcopy(custom)
        values["config"] = {"ui": copy.deepcopy(DIRECT)}
        values["config"]["ui"]["browser_session"]["backend"] = {"type": "memory"}
        values.pop("valkey")
        values.pop("browserState")
        self.assertIn("autoscaling.maxReplicas: 1", render(values, failed=True))
        values["autoscaling"].update({"minReplicas": 1, "maxReplicas": 1})
        values["replicaCount"] = 5
        self.assertNotIn("replicas", app(render(values))["spec"])
        bundled = copy.deepcopy(BUNDLED)
        bundled.update(copy.deepcopy(custom))
        bundled["config"] = {"ui": copy.deepcopy(DIRECT)}
        docs = render(bundled)
        valkey = next(d for d in docs if d["kind"] == "Deployment" and d != app(docs))
        self.assertEqual(valkey["spec"]["replicas"], 1)
        self.assertEqual(valkey["spec"]["strategy"]["type"], "Recreate")
        sentinel = "DO_NOT_LEAK_PASSWORD_12345"
        bundled["config"]["ui"]["browser_session"]["backend"]["password"] = sentinel
        self.assertNotIn(sentinel, render(bundled, failed=True))

    def test_rejections_and_secret_redaction(self):
        sentinel = "DO_NOT_LEAK_PASSWORD_12345"
        cases = [
            {
                "config": {
                    "ui": {
                        "browser_session": {
                            "backend": {"type": "valkey", "password": sentinel}
                        }
                    }
                }
            },
            {
                "config": {
                    "ui": {
                        "browser_session": {
                            "backend": {
                                "type": "valkey",
                                "url": f"redis://:{sentinel}@primary:6379/0",
                            }
                        }
                    }
                }
            },
            {"extraEnv": [{"name": PASSWORD_ENV, "value": sentinel}]},
            {
                "browserState": BUNDLED["browserState"],
                "extraEnv": [
                    {
                        "name": PASSWORD_ENV,
                        "valueFrom": {
                            "secretKeyRef": {"name": "duplicate", "key": "password"}
                        },
                    }
                ],
            },
            {"config": {"ui": {"enabled": True, "basic": {"provider_name": "basic"}}}},
            {"config": {"ui": {"enabled": False, "basic": {"provider_name": "basic"}}}},
            {"config": {"ui": {"browser_session": {"session_ttl_seconds": 86401}}}},
            {"config": {"ui": {"browser_session": {"transaction_ttl_seconds": 29}}}},
            {
                "config": {
                    "ui": {
                        "browser_session": {
                            "backend": {"type": "valkey", "operation_timeout_ms": 0}
                        }
                    }
                }
            },
            {"browserState": {"password": sentinel}},
        ]
        for values in cases:
            self.assertNotIn(sentinel, render(values, failed=True))
        external = {
            "config": {"ui": copy.deepcopy(DIRECT)},
            "browserState": copy.deepcopy(BUNDLED["browserState"]),
        }
        external["config"]["ui"]["browser_session"]["backend"]["url"] = (
            "redis://primary:6379/0"
        )
        password_env = {
            "name": PASSWORD_ENV,
            "valueFrom": {"secretKeyRef": {"name": "external", "key": "password"}},
        }
        external.pop("browserState")
        external["extraEnv"] = [password_env]
        self.assertEqual(
            app(render(external))["spec"]["template"]["spec"]["containers"][0]["env"],
            [password_env],
        )
        external["extraEnv"] = [password_env, copy.deepcopy(password_env)]
        self.assertIn("at most one secretKeyRef", render(external, failed=True))
        external["extraEnv"][1]["value"] = sentinel
        self.assertNotIn(sentinel, render(external, failed=True))

        bounds = {
            "session_ttl_seconds": (60, 86400),
            "transaction_ttl_seconds": (30, 900),
            "max_forms": (1, 100000),
            "max_sessions": (1, 100000),
            "max_forms_per_window": (1, 100000),
            "max_logins_per_window": (1, 100000),
            "rate_window_seconds": (1, 3600),
            "max_inflight_logins": (1, 256),
            "max_shared_inflight_logins": (1, 65536),
            "verification_timeout_seconds": (1, 30),
            "connect_timeout_ms": (1, 30000),
            "operation_timeout_ms": (1, 10000),
        }
        for field, (minimum, maximum) in bounds.items():
            for value in [minimum - 1, minimum, maximum, maximum + 1]:
                with self.subTest(field=field, value=value):
                    values = copy.deepcopy(BUNDLED)
                    values["config"] = {"ui": copy.deepcopy(DIRECT)}
                    target = values["config"]["ui"]["browser_session"]
                    if field.endswith("_ms"):
                        target = target["backend"]
                    target[field] = value
                    docs = render(
                        values, failed=value not in range(minimum, maximum + 1)
                    )
                    if minimum <= value <= maximum:
                        session = config(docs)["ui"]["browser_session"]
                        self.assertEqual(
                            (session["backend"] if field.endswith("_ms") else session)[
                                field
                            ],
                            value,
                        )
                    else:
                        self.assertIn("schema", docs)
        values = copy.deepcopy(BUNDLED)
        values["config"] = {"ui": copy.deepcopy(DIRECT)}
        values["config"]["ui"]["browser_session"]["max_shared_inflight_logins"] = None
        self.assertIsNone(
            config(render(values))["ui"]["browser_session"].get(
                "max_shared_inflight_logins"
            )
        )
        for prefix in ["", "x" * 129, "a b", "a{tag}", "名", "a.b", "a/b"]:
            values = copy.deepcopy(BUNDLED)
            values["config"] = {"ui": copy.deepcopy(DIRECT)}
            values["config"]["ui"]["browser_session"]["backend"]["key_prefix"] = prefix
            self.assertIn("schema", render(values, failed=True))
        values["config"]["ui"]["browser_session"]["backend"]["key_prefix"] = "A" * 128
        self.assertEqual(
            config(render(values))["ui"]["browser_session"]["backend"]["key_prefix"],
            "A" * 128,
        )
        for missing in ["backend", "public_origin"]:
            values = copy.deepcopy(BUNDLED)
            values["config"] = {"ui": copy.deepcopy(DIRECT)}
            del values["config"]["ui"]["browser_session"][missing]
            self.assertIn("schema", render(values, failed=True))
        for origin in [
            "/login",
            "https://login.test/path",
            "https://login.test/?q=x",
            f"https://:{sentinel}@login.test",
        ]:
            values = copy.deepcopy(BUNDLED)
            values["config"] = {"ui": copy.deepcopy(DIRECT)}
            values["config"]["ui"]["browser_session"]["public_origin"] = origin
            error = render(values, failed=True)
            self.assertIn("absolute HTTPS origin", error)
            self.assertNotIn(sentinel, error)
        for field in [
            "url",
            "password",
            "key_prefix",
            "connect_timeout_ms",
            "operation_timeout_ms",
        ]:
            values = {"config": {"ui": copy.deepcopy(DIRECT)}}
            values["config"]["ui"]["browser_session"]["backend"] = {
                "type": "memory",
                field: "",
            }
            self.assertIn("schema", render(values, failed=True))
        values = {
            "config": {"ui": copy.deepcopy(DIRECT)},
            "browserState": copy.deepcopy(BUNDLED["browserState"]),
        }
        self.assertIn("external Valkey requires", render(values, failed=True))
        replacement = copy.deepcopy(BUNDLED)
        replacement["valkey"]["deploymentStrategy"] = "RollingUpdate"
        self.assertIn(
            "requires deploymentStrategy: Recreate", render(replacement, failed=True)
        )
        for override in [
            {"service": {"type": "LoadBalancer"}},
            {"replica": {"enabled": True}},
            {"auth": {"enabled": False}},
            {"auth": {"usersExistingSecret": "wrong-secret"}},
            {"auth": {"aclUsers": {"default": {"password": sentinel}}}},
            {"networkPolicy": {"ingress": [{"from": [{"namespaceSelector": {}}]}]}},
        ]:
            values = copy.deepcopy(BUNDLED)
            for key, value in override.items():
                if isinstance(value, dict):
                    values["valkey"].setdefault(key, {}).update(value)
                else:
                    values["valkey"][key] = value
            self.assertNotIn(sentinel, render(values, failed=True))

    def test_parent_subchart_scope(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            parent = Path(tmp)
            (parent / "charts").mkdir()
            (parent / "Chart.yaml").write_text(
                "apiVersion: v2\nname: parent\nversion: 1.0.0\ndependencies:\n- name: auth-o-tron-chart\n  alias: gateway\n  version: 0.3.4\n"
            )
            subprocess.run(
                [
                    "helm",
                    "package",
                    str(CHART),
                    "--destination",
                    str(parent / "charts"),
                ],
                check=True,
                capture_output=True,
                env={**os.environ, **HOMES},
            )
            values = copy.deepcopy(BUNDLED)
            values["config"] = {"ui": DIRECT}
            values["autoscaling"] = {"enabled": True}
            values["resources"] = {"requests": {"cpu": "100m"}}
            docs = render({"gateway": values}, chart=parent)
            self.assertEqual(
                config(docs)["ui"]["browser_session"]["backend"]["url"],
                "redis://aot-valkey:6379/0",
            )
            self.assertEqual(len([d for d in docs if d["kind"] == "NetworkPolicy"]), 1)
            hpa = next(d for d in docs if d["kind"] == "HorizontalPodAutoscaler")
            deployment = next(
                d
                for d in docs
                if d["kind"] == "Deployment"
                and d["spec"]["template"]["spec"]["containers"][0]["name"] == "gateway"
            )
            self.assertEqual(
                hpa["spec"]["scaleTargetRef"]["name"], deployment["metadata"]["name"]
            )
            self.assertNotIn("replicas", deployment["spec"])
            # Two instances in one parent release share an external primary but
            # must not share a default browser namespace, even with equal fullnames.
            (parent / "Chart.yaml").write_text(
                "apiVersion: v2\nname: parent\nversion: 1.0.0\ndependencies:\n- name: auth-o-tron-chart\n  alias: gateway\n  version: 0.3.4\n- name: auth-o-tron-chart\n  alias: second\n  version: 0.3.4\n"
            )
            values["valkey"] = {"enabled": False}
            values["config"] = {"ui": copy.deepcopy(DIRECT)}
            values["config"]["ui"]["browser_session"]["backend"]["url"] = (
                "redis://shared-primary:6379/0"
            )
            docs = render(
                {"gateway": values, "second": copy.deepcopy(values)}, chart=parent
            )
            prefixes = [
                yaml.safe_load(d["data"]["config.yaml"])["ui"]["browser_session"][
                    "backend"
                ]["key_prefix"]
                for d in docs
                if d["kind"] == "ConfigMap" and "config.yaml" in d["data"]
            ]
            self.assertEqual(len(prefixes), 2)
            self.assertEqual(len(set(prefixes)), 2)
            changed = copy.deepcopy(values)
            changed["replicaCount"] = 4
            changed["config"]["ui"]["browser_session"]["session_ttl_seconds"] = 1200
            stable = render({"gateway": changed, "second": values}, chart=parent)
            stable_prefixes = [
                yaml.safe_load(d["data"]["config.yaml"])["ui"]["browser_session"][
                    "backend"
                ]["key_prefix"]
                for d in stable
                if d["kind"] == "ConfigMap" and "config.yaml" in d["data"]
            ]
            self.assertEqual(prefixes, stable_prefixes)

    def test_vendor_digest_and_lock(self):
        self.assertEqual(
            hashlib.sha256(
                (CHART / "charts/valkey-0.12.0.tgz").read_bytes()
            ).hexdigest(),
            "64d43433d6b80addb012dd7c21a1bf674bf034dc51210b6bf8eae9ddaf83740f",
        )
        lock = yaml.safe_load((CHART / "Chart.lock").read_text())
        self.assertEqual(
            [(d["name"], d["version"]) for d in lock["dependencies"]],
            [("mongodb", "16.4.2"), ("valkey", "0.12.0")],
        )
        json.loads((CHART / "values.schema.json").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
