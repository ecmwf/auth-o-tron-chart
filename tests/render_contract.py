"""Offline render contracts. Run: python3 tests/render_contract.py (Helm + PyYAML)."""

import copy
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

CHART = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((CHART / "values.schema.json").read_text())
DEFS = SCHEMA["definitions"]
SESSION = DEFS["authotron.BrowserSessionConfig"]["properties"]
VALKEY_BACKEND = DEFS["authotron.BrowserBackendConfig"]["oneOf"][1]["properties"]
PASSWORD_ENV = "AOT_UI__BROWSER_SESSION__BACKEND__PASSWORD"
HOMES = {}


def setUpModule():
    root = tempfile.TemporaryDirectory(prefix="authotron-helm-")
    unittest.addModuleCleanup(root.cleanup)
    HOMES.update(
        {
            f"HELM_{kind}_HOME": str(Path(root.name) / kind.lower())
            for kind in ("CACHE", "CONFIG", "DATA")
        }
    )


BUNDLED = {
    "valkey": {"enabled": True, "auth": {"usersExistingSecret": "browser-secret"}},
    "browserState": {"passwordSecret": {"name": "browser-secret", "key": "default"}},
}
BROWSER_PROVIDER = {
    "type": "plain",
    "name": "basic-provider",
    "realm": "browser",
    "users": [],
    "browser": {"id": "password", "label": "Username and password"},
}
DIRECT = {
    "enabled": True,
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
        check=False,
    )
    if failed:
        assert result.returncode, "render unexpectedly succeeded"
        return result.stdout + result.stderr
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def schema_failure(error, path, message=""):
    """Assert a schema rejection names `path` (Helm 4 JSON pointer, Helm 3 dots).

    Example: path "config/providers/0/browser/id" matches Helm 4's
    "at '/config/providers/0/browser/id': ..." and Helm 3's
    "config.providers.0.browser.id: ...".
    """
    assert "schema" in error, error
    assert "execution error" not in error, error
    lines = [line.replace("/", ".") for line in error.splitlines()]
    dotted = path.replace("/", ".")
    hits = [line for line in lines if dotted in line and message in line]
    assert hits, f"no schema error at {path!r} containing {message!r}:\n{error}"


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


def numeric_bounds(properties):
    return {
        name: (prop["minimum"], prop["maximum"])
        for name, prop in properties.items()
        if "minimum" in prop and "maximum" in prop
    }


def browser_provider(index, **browser):
    provider = copy.deepcopy(BROWSER_PROVIDER)
    provider["name"] = f"provider-{index}"
    provider["browser"] = {"id": f"method-{index}", "label": f"Method {index}"}
    provider["browser"].update(browser)
    return provider


def direct_config(ui=None):
    """Chart config with one browser-enabled provider and a direct-login UI."""
    return {
        "providers": [copy.deepcopy(BROWSER_PROVIDER)],
        "ui": copy.deepcopy(DIRECT) if ui is None else ui,
    }


class Contracts(unittest.TestCase):
    def assert_unique_resources(self, docs):
        identities = [
            (
                doc["kind"],
                doc["metadata"].get("namespace", "contract"),
                doc["metadata"]["name"],
            )
            for doc in docs
        ]
        self.assertEqual(len(identities), len(set(identities)), identities)

    def assert_workload_isolation(self, docs):
        self.assert_unique_resources(docs)
        deployments = [doc for doc in docs if doc["kind"] == "Deployment"]

        def selected(selector, namespace):
            self.assertTrue(selector)
            return [
                deployment["metadata"]["name"]
                for deployment in deployments
                if deployment["metadata"].get("namespace", "contract") == namespace
                and selector.items()
                <= deployment["spec"]["template"]["metadata"]["labels"].items()
            ]

        for doc in docs:
            namespace = doc["metadata"].get("namespace", "contract")
            if doc["kind"] == "Deployment":
                self.assertEqual(
                    selected(doc["spec"]["selector"]["matchLabels"], namespace),
                    [doc["metadata"]["name"]],
                )
            elif doc["kind"] == "Service":
                self.assertEqual(
                    len(selected(doc["spec"]["selector"], namespace)), 1, doc
                )

    def test_bundled_selector_collisions(self):
        for overrides in [
            {"nameOverride": "valkey"},
            {"valkey": {"nameOverride": "auth-o-tron"}},
            {"nameOverride": "shared", "valkey": {"nameOverride": "shared"}},
            {
                "nameOverride": "s" * 63 + "-app",
                "valkey": {"nameOverride": "s" * 63 + "-state"},
            },
        ]:
            values = copy.deepcopy(BUNDLED)
            values.update(
                {key: value for key, value in overrides.items() if key != "valkey"}
            )
            values["valkey"].update(overrides.get("valkey", {}))
            values["valkey"]["fullnameOverride"] = "distinct-state"
            self.assertIn("pod selectors must differ", render(values, failed=True))
        values["nameOverride"] = "gateway"
        self.assert_workload_isolation(render(values))

    def test_bundled_selector_label_overrides(self):
        for field in ["commonLabels", "podLabels"]:
            for key, value in [
                ("app.kubernetes.io/name", "auth-o-tron"),
                ("app.kubernetes.io/instance", "another-release"),
            ]:
                with self.subTest(field=field, key=key):
                    values = copy.deepcopy(BUNDLED)
                    values["valkey"][field] = {key: value}
                    self.assertIn(
                        "must not override selector labels", render(values, failed=True)
                    )
            values["valkey"][field] = {
                "app.kubernetes.io/name": "valkey",
                "app.kubernetes.io/instance": "aot",
                "team": "identity",
            }
            self.assert_workload_isolation(render(values))

    def test_bundled_metrics_service_collision(self):
        values = copy.deepcopy(BUNDLED)
        values["fullnameOverride"] = "state-metrics"
        values["valkey"].update(
            {"fullnameOverride": "state", "metrics": {"enabled": True}}
        )
        self.assertIn("metrics Service name", render(values, failed=True))
        values["valkey"]["metrics"]["service"] = {"enabled": False}
        self.assert_workload_isolation(render(values))
        values["valkey"]["metrics"]["service"]["enabled"] = True
        values["valkey"]["metrics"]["enabled"] = False
        self.assert_workload_isolation(render(values))
        values["valkey"]["metrics"]["enabled"] = True
        values["fullnameOverride"] = "gateway"
        values["valkey"]["metrics"].update(
            {
                "serviceMonitor": {"enabled": True},
                "podMonitor": {"enabled": True},
            }
        )
        docs = render(values)
        self.assert_workload_isolation(docs)
        self.assertEqual(len([doc for doc in docs if doc["kind"] == "Service"]), 3)

    def test_metrics_service_fullname_length(self):
        values = copy.deepcopy(BUNDLED)
        values["valkey"].update(
            {"fullnameOverride": "s" * 55, "metrics": {"enabled": True}}
        )
        docs = render(values)
        self.assert_workload_isolation(docs)
        self.assertTrue(
            all(
                len(doc["metadata"]["name"]) <= 63
                for doc in docs
                if doc["kind"] == "Service"
            )
        )
        for length in (56, 58):
            values["valkey"]["fullnameOverride"] = "s" * length
            self.assertIn("at most 55 characters", render(values, failed=True))
        values["valkey"]["metrics"]["service"] = {"enabled": False}
        self.assert_workload_isolation(render(values))
        values["valkey"]["metrics"] = {"enabled": False}
        self.assert_workload_isolation(render(values))

    def test_fullname_collisions(self):
        for release, overrides in [
            ("auth-o-tron-valkey", {}),
            ("valkey-auth-o-tron", {}),
            (
                "aot",
                {
                    "fullnameOverride": "same",
                    "valkey": {**BUNDLED["valkey"], "fullnameOverride": "same"},
                },
            ),
        ]:
            with self.subTest(release=release):
                values = {**copy.deepcopy(BUNDLED), **overrides}
                self.assertIn(
                    "fullnames must differ", render(values, release, failed=True)
                )
                values["valkey"]["fullnameOverride"] = "distinct-state"
                docs = render(values, release)
                self.assert_workload_isolation(docs)

    def test_generated_schema_is_current_and_hpa_matches_server(self):
        source = SCHEMA["properties"]["config"]["x-authotron-source"]
        self.assertRegex(source["commit"], r"^[0-9a-f]{40}$")
        self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$")
        server = SCHEMA["properties"]["config"]
        self.assertNotIn("$defs", json.dumps(server))
        inflight = SESSION["max_inflight_logins"]
        target = SCHEMA["properties"]["autoscaling"]["properties"][
            "targetInFlightLogins"
        ]
        self.assertEqual(
            (target["minimum"], target["maximum"]),
            (inflight["minimum"], inflight["maximum"]),
        )
        cap = inflight["default"]
        hpa = (CHART / "templates/hpa.yaml").read_text()
        self.assertIn(f"default {cap} $session.max_inflight_logins", hpa)
        self.assertIn(f"(default {cap})", hpa)
        self.assertIn(
            f"must be below max_inflight_logins (default {cap})",
            (CHART / "values.yaml").read_text(),
        )
        values = copy.deepcopy(BUNDLED)
        values["config"] = direct_config()
        values["autoscaling"] = {
            "enabled": True,
            "targetCPUUtilizationPercentage": None,
            "targetInFlightLogins": cap - 1,
        }
        render(values)
        values["autoscaling"]["targetInFlightLogins"] = cap
        self.assertIn("strictly below effective", render(values, failed=True))

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
        self.assertNotIn("env", app(docs)["spec"]["template"]["spec"]["containers"][0])
        self.assertFalse(
            any(d["kind"] in ("Ingress", "StatefulSet", "Secret") for d in docs)
        )
        claims = [d for d in docs if d["kind"] == "PersistentVolumeClaim"]
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["spec"]["accessModes"], ["ReadWriteOnce"])
        self.assertEqual(claims[0]["spec"]["resources"]["requests"]["storage"], "1Gi")
        self.assertNotIn("storageClassName", claims[0]["spec"])
        valkey_conf = next(
            d["data"]["valkey.conf"]
            for d in docs
            if d["kind"] == "ConfigMap" and "valkey.conf" in d.get("data", {})
        ).splitlines()
        for line in ("appendonly yes", "appendfsync everysec", 'save ""'):
            self.assertIn(line, valkey_conf)
        ephemeral = copy.deepcopy(BUNDLED)
        ephemeral["valkey"]["dataStorage"] = {"enabled": False}
        self.assertFalse(
            any(d["kind"] == "PersistentVolumeClaim" for d in render(ephemeral))
        )
        values = copy.deepcopy(BUNDLED)
        values["extraEnv"] = [{"name": "RUST_LOG", "value": "info"}]
        for ui in [
            {},
            {"enabled": True},
            {
                "browser_session": {
                    "public_origin": "https://login.example.test",
                    "backend": {"type": "memory"},
                }
            },
        ]:
            with self.subTest(ui=ui):
                values["config"] = {"ui": ui}
                docs = render(values)
                self.assertEqual(config(docs)["ui"], ui)
                self.assertEqual(
                    app(docs)["spec"]["template"]["spec"]["containers"][0]["env"],
                    values["extraEnv"],
                )

    def test_null_browser_provider_is_api_only(self):
        provider = dict(BROWSER_PROVIDER, browser=None)
        docs = render({"config": {"providers": [provider], "ui": {"enabled": True}}})
        self.assertEqual(config(docs)["providers"][0]["browser"], None)
        self.assertNotIn("browser_session", config(docs)["ui"])
        self.assertFalse(any(d["kind"] == "StatefulSet" for d in docs))

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
                values["config"] = direct_config()
                # Bundled helper must replace a stale supplied URL.
                values["config"]["ui"]["browser_session"]["backend"]["url"] = (
                    "redis://stale:6379/0"
                )
                values["replicaCount"] = 2
                docs = render(values, release)
                self.assert_workload_isolation(docs)
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
                    backend["key_prefix"], r"^authotron:browser:[0-9a-f]{32}$"
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
                self.assertIn(
                    {
                        "name": "valkey-data",
                        "persistentVolumeClaim": {
                            "claimName": valkey["metadata"]["name"]
                        },
                    },
                    spec["volumes"],
                )
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
            "config": direct_config(ui),
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
        self.assertRegex(longest, r"^authotron:browser:[0-9a-f]{32}$")
        self.assertEqual(len(longest), 50)
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
        values["config"] = direct_config()
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
        bundled["config"] = direct_config()
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
        memory = {"config": direct_config()}
        memory["config"]["ui"]["browser_session"]["backend"] = {"type": "memory"}
        preview = {"config": {"ui": {"enabled": True}}, "ingress": {"enabled": True}}
        bundled_metrics = copy.deepcopy(bundled)
        bundled_metrics["valkey"]["metrics"] = {"enabled": True}
        for values in [
            {},
            preview,
            BUNDLED,
            bundled,
            external,
            memory,
            cpu_hpa,
            custom_hpa,
            bundled_metrics,
        ]:
            result = subprocess.run(
                ["helm", "lint", "--strict", str(CHART), "-f", "-"],
                input=yaml.safe_dump(values),
                text=True,
                capture_output=True,
                env={**os.environ, **HOMES},
                check=False,
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
        values["config"] = direct_config()
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
            # Helm 3 uses dotted schema paths; Helm 4 uses JSON-pointer paths.
            self.assertIn("resources.requests.cpu", error.replace("/", "."))
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
        custom["config"] = direct_config()
        custom["autoscaling"] = {
            "enabled": True,
            "targetCPUUtilizationPercentage": None,
            "targetInFlightLogins": 4,
        }
        render(custom)  # Positive target below the implicit per-pod default of 8.
        absent = copy.deepcopy(custom)
        absent["config"].pop("ui")
        self.assertIn("provider with a browser block", render(absent, failed=True))
        api_only = copy.deepcopy(BROWSER_PROVIDER)
        api_only.pop("browser")
        for providers, inactive in [
            ([api_only], {}),
            ([api_only], {"enabled": True}),
            (
                [api_only],
                {
                    "enabled": True,
                    "sso": [{"label": "SSO", "start_url": "/oauth2/start"}],
                },
            ),
            ([api_only], copy.deepcopy(DIRECT)),
            ([BROWSER_PROVIDER], {**copy.deepcopy(DIRECT), "enabled": False}),
        ]:
            values = copy.deepcopy(custom)
            values["config"]["providers"] = copy.deepcopy(providers)
            values["config"]["ui"] = inactive
            self.assertIn("provider with a browser block", render(values, failed=True))
        for cap, target in [(None, 8), (None, 9), (1, 1), (4, 4), (4, 5)]:
            values = copy.deepcopy(custom)
            values["autoscaling"]["targetInFlightLogins"] = target
            if cap is not None:
                values["config"]["ui"]["browser_session"]["max_inflight_logins"] = cap
            self.assertIn("strictly below effective", render(values, failed=True))
        ecmwf = copy.deepcopy(custom)
        ecmwf["config"]["providers"] = [
            {
                "type": "ecmwf-api",
                "name": "ECMWF API Provider",
                "realm": "ecmwf",
                "uri": "https://api.ecmwf.int/v1",
                "browser": {
                    "label": "ECMWF API key",
                    "id": "api-key",
                },
            }
        ]
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
        values["config"] = direct_config()
        values["config"]["ui"]["browser_session"]["backend"] = {"type": "memory"}
        values.pop("valkey")
        values.pop("browserState")
        self.assertIn("autoscaling.maxReplicas: 1", render(values, failed=True))
        values["autoscaling"].update({"minReplicas": 1, "maxReplicas": 1})
        values["replicaCount"] = 5
        self.assertNotIn("replicas", app(render(values))["spec"])
        bundled = copy.deepcopy(BUNDLED)
        bundled.update(copy.deepcopy(custom))
        bundled["config"] = direct_config()
        docs = render(bundled)
        valkey = next(d for d in docs if d["kind"] == "Deployment" and d != app(docs))
        self.assertEqual(valkey["spec"]["replicas"], 1)
        self.assertEqual(valkey["spec"]["strategy"]["type"], "Recreate")
        sentinel = "DO_NOT_LEAK_PASSWORD_12345"
        bundled["config"]["ui"]["browser_session"]["backend"]["password"] = sentinel
        self.assertNotIn(sentinel, render(bundled, failed=True))

    def test_generated_schema_rejections(self):
        def schema_error(provider=None, ui=None, path="config", message=""):
            values = copy.deepcopy(BUNDLED)
            values["config"] = direct_config(ui)
            if provider is not None:
                values["config"]["providers"] = [provider]
            schema_failure(render(values, failed=True), path, message)

        label_path = "config/providers/0/browser/label"
        for label in ["", "x" * 65]:
            with self.subTest(label=label):
                schema_error(browser_provider(1, label=label), path=label_path)
        schema_error(
            browser_provider(1, unknown=True),
            path="config/providers/0/browser",
            message="unknown",
        )
        schema_error(browser_provider(1, label=7), path=label_path, message="string")
        schema_error(
            dict(browser_provider(1), browser="password"),
            path="config/providers/0/browser",
        )
        schema_error(
            dict(browser_provider(1), type="unknown"),
            path="config/providers/0/type",
        )
        schema_error(
            dict(BROWSER_PROVIDER, users="alice"), path="config/providers/0/users"
        )
        # Only plain and ecmwf-api accept a browser block; null stays API-only.
        jwt = {
            "type": "jwt",
            "name": "sso",
            "realm": "sso",
            "cert_uri": "https://sso.example.test/certs",
            "iam_realm": "sso",
        }
        values = copy.deepcopy(BUNDLED)
        values["config"] = direct_config()
        values["config"]["providers"].append(
            dict(jwt, browser={"id": "sso", "label": "SSO"})
        )
        schema_failure(render(values, failed=True), "config/providers/1/browser")
        values["config"]["providers"][-1]["browser"] = None
        rendered = config(render(values))["providers"][-1]
        self.assertIsNone(rendered["browser"])
        for removed in ["sign_in_actions", "ecmwf_api_key", "basic"]:
            with self.subTest(removed=removed):
                schema_error(
                    ui={**copy.deepcopy(DIRECT), removed: {}},
                    path="config/ui",
                    message=removed,
                )
        schema_failure(
            render({"config": {"version": "3.0.0"}}, failed=True), "config/version"
        )
        # Chart defaults must satisfy the server's required ConfigV2 fields.
        schema_failure(render({"config": {"jwt": None}}, failed=True), "config")

    def test_browser_id_schema_rejections(self):
        for bad in ["", "-a", "A", "a_b", "a" * 33, "callback", "new", "account"]:
            with self.subTest(id=bad):
                values = copy.deepcopy(BUNDLED)
                values["config"] = direct_config()
                values["config"]["providers"] = [browser_provider(1, id=bad)]
                schema_failure(
                    render(values, failed=True), "config/providers/0/browser/id"
                )
        values = copy.deepcopy(BUNDLED)
        values["config"] = direct_config()
        values["config"]["providers"] = [browser_provider(1, id="a" * 32)]
        render(values)

    def test_cross_provider_browser_rules(self):
        def providers_result(providers, failed):
            values = copy.deepcopy(BUNDLED)
            values["config"] = direct_config()
            values["config"]["providers"] = providers
            return render(values, failed=failed)

        providers_result([browser_provider(i) for i in range(16)], False)
        self.assertIn(
            "at most 16 browser methods",
            providers_result([browser_provider(i) for i in range(17)], True),
        )
        api_only = [dict(browser_provider(i), browser=None) for i in range(20)]
        providers_result([browser_provider(99), *api_only], False)
        for label in ["Method 1", "method 1", "  METHOD 1 "]:
            with self.subTest(label=label):
                duplicate = [browser_provider(1), browser_provider(2, label=label)]
                self.assertIn(
                    "labels must be unique", providers_result(duplicate, True)
                )
        # Case folding is Unicode-aware: "Ärzte" and "ärzte" collide.
        non_ascii = [
            browser_provider(1, label="Ärzte"),
            browser_provider(2, label="ärzte"),
        ]
        self.assertIn("labels must be unique", providers_result(non_ascii, True))
        distinct = [
            browser_provider(1, label="Ärzte"),
            browser_provider(2, label="Aerzte"),
        ]
        providers_result(distinct, False)
        duplicate = [browser_provider(1), browser_provider(2, id="method-1")]
        self.assertIn(
            'browser method id "method-1" must be unique',
            providers_result(duplicate, True),
        )
        for ui in [{"enabled": True}, {"enabled": True, "browser_session": None}]:
            with self.subTest(ui=ui):
                values = {"config": direct_config(ui)}
                self.assertIn(
                    "requires config.ui.browser_session.backend.type",
                    render(values, failed=True),
                )

    def test_oidc_methods_share_browser_rules_and_need_distinct_realms(self):
        def oidc(index, **fields):
            method = {
                "id": f"sso-{index}",
                "label": f"SSO {index}",
                "realm": f"idp-{index}",
                "issuer": "https://idp.example.test/realms/demo",
                "client_id": "authotron",
                "client_auth": "none",
            }
            method.update(fields)
            return method

        def oidc_result(methods, failed, providers=None):
            values = copy.deepcopy(BUNDLED)
            values["config"] = direct_config()
            if providers is not None:
                values["config"]["providers"] = providers
            values["config"]["ui"]["oidc"] = methods
            return render(values, failed=failed)

        docs = oidc_result([oidc(1)], False, providers=[])
        self.assertEqual(config(docs)["ui"]["oidc"], [oidc(1)])
        self.assertIn(
            "requires config.ui.browser_session.backend.type",
            render(
                {
                    "config": {
                        "providers": [],
                        "ui": {"enabled": True, "oidc": [oidc(1)]},
                    }
                },
                failed=True,
            ),
        )
        oidc_result([oidc(i) for i in range(15)], False)
        self.assertIn(
            "at most 16 browser methods",
            oidc_result([oidc(i) for i in range(16)], True),
        )
        for method, error in [
            (oidc(1, id="password"), 'browser method id "password" must be unique'),
            (oidc(1, label="USERNAME AND PASSWORD"), "labels must be unique"),
            (oidc(1, realm="browser"), 'ui.oidc realm "browser" must differ'),
        ]:
            with self.subTest(method=method):
                self.assertIn(error, oidc_result([method], True))
        self.assertIn(
            'ui.oidc realm "idp-1" must differ',
            oidc_result([oidc(1), oidc(2, realm="idp-1")], True),
        )
        schema_failure(
            oidc_result([oidc(1, id="callback")], True), "config/ui/oidc/0/id"
        )
        schema_failure(
            oidc_result([oidc(1, client_secret="inline")], True), "config/ui/oidc/0"
        )

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
            {
                "config": {
                    "providers": [copy.deepcopy(BROWSER_PROVIDER)],
                    "ui": {"enabled": True},
                }
            },
            {
                "config": {
                    "providers": [copy.deepcopy(BROWSER_PROVIDER)],
                    "ui": {"enabled": False},
                }
            },
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
            "config": direct_config(),
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

        bounds = {**numeric_bounds(SESSION), **numeric_bounds(VALKEY_BACKEND)}
        self.assertGreaterEqual(len(bounds), 12)
        for field, (minimum, maximum) in bounds.items():
            for value in [minimum - 1, minimum, maximum, maximum + 1]:
                with self.subTest(field=field, value=value):
                    values = copy.deepcopy(BUNDLED)
                    values["config"] = direct_config()
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
        values["config"] = direct_config()
        values["config"]["ui"]["browser_session"]["max_shared_inflight_logins"] = None
        self.assertIsNone(
            config(render(values))["ui"]["browser_session"].get(
                "max_shared_inflight_logins"
            )
        )
        for prefix in ["", "x" * 129, "a b", "a{tag}", "名", "a.b", "a/b"]:
            values = copy.deepcopy(BUNDLED)
            values["config"] = direct_config()
            values["config"]["ui"]["browser_session"]["backend"]["key_prefix"] = prefix
            schema_failure(
                render(values, failed=True),
                "config/ui/browser_session/backend/key_prefix",
            )
        values["config"]["ui"]["browser_session"]["backend"]["key_prefix"] = "A" * 128
        self.assertEqual(
            config(render(values))["ui"]["browser_session"]["backend"]["key_prefix"],
            "A" * 128,
        )
        for missing in ["backend", "public_origin"]:
            values = copy.deepcopy(BUNDLED)
            values["config"] = direct_config()
            del values["config"]["ui"]["browser_session"][missing]
            schema_failure(
                render(values, failed=True),
                "config/ui/browser_session",
                f"missing property '{missing}'",
            )
        for origin in [
            "/login",
            "https://login.test/path",
            "https://login.test/?q=x",
            f"https://:{sentinel}@login.test",
        ]:
            values = copy.deepcopy(BUNDLED)
            values["config"] = direct_config()
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
            values = {"config": direct_config()}
            values["config"]["ui"]["browser_session"]["backend"] = {
                "type": "memory",
                field: "",
            }
            schema_failure(
                render(values, failed=True),
                "config/ui/browser_session/backend",
                field,
            )
        values = {
            "config": direct_config(),
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
        with tempfile.TemporaryDirectory(prefix="authotron-parent-") as tmp:
            parent = Path(tmp)
            (parent / "charts").mkdir()
            (parent / "Chart.yaml").write_text(
                "apiVersion: v2\nname: parent\nversion: 1.0.0\ndependencies:\n"
                "- name: auth-o-tron-chart\n  alias: gateway\n  version: 0.5.0\n"
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
            values["config"] = direct_config()
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
                "apiVersion: v2\nname: parent\nversion: 1.0.0\ndependencies:\n"
                "- name: auth-o-tron-chart\n  alias: gateway\n  version: 0.5.0\n"
                "- name: auth-o-tron-chart\n  alias: second\n  version: 0.5.0\n"
            )
            values["valkey"] = {"enabled": False}
            values["config"] = direct_config()
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
