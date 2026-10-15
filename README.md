![Auth-O-Tron](https://raw.githubusercontent.com/ecmwf/auth-o-tron/main/authotron/docs/logo-light.png)

<div align="center">

[![ECMWF](https://github.com/ecmwf/codex/raw/refs/heads/main/ESEE/foundation_badge.svg)](https://github.com/ecmwf/codex/raw/refs/heads/main/ESEE)
[![Maturity](https://github.com/ecmwf/codex/raw/refs/heads/main/Project%20Maturity/emerging_badge.svg)](https://github.com/ecmwf/codex/raw/refs/heads/main/Project%20Maturity)

</div>

# Auth-O-Tron Helm Chart

Helm chart for deploying [Auth-O-Tron](https://github.com/ecmwf/auth-o-tron) on Kubernetes, an authentication and authorization gateway for web APIs.

## Installation

```bash
git clone https://github.com/ecmwf/auth-o-tron-chart.git
helm install auth-o-tron ./auth-o-tron-chart
```

## Configuration

All configuration is done through `values.yaml`. See below for key settings.

### Image

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image.repository` | Container image repository | `eccr.ecmwf.int/auth-o-tron/auth-o-tron` |
| `image.tag` | Image tag | `0.3.6` |
| `image.pullPolicy` | Pull policy | `IfNotPresent` |

### Service

| Parameter | Description | Default |
|-----------|-------------|---------|
| `service.type` | Service type | `ClusterIP` |
| `service.port` | Client-facing port | `8080` |
| `service.targetPort` | Container listen port (must match `config.server.port`) | `8080` |
| `service.annotations` | Service annotations | `{}` |

### Ingress

| Parameter | Description | Default |
|-----------|-------------|---------|
| `ingress.enabled` | Enable Ingress resource | `false` |
| `ingress.className` | Ingress class name | `""` |
| `ingress.annotations` | Ingress annotations | `{}` |
| `ingress.hosts` | Ingress host rules | `[{host: auth-o-tron.local, paths: [{path: /, pathType: Prefix}]}]` |
| `ingress.tls` | TLS configuration | `[]` |

Only the application port is routed via Ingress. The metrics port is not included in the Ingress rules. In production, enable TLS and consider restricting ingress paths to only the endpoints you need exposed (e.g. `/authenticate`, `/health`).

### Metrics

| Parameter | Description | Default |
|-----------|-------------|---------|
| `metrics.enabled` | Enable dedicated metrics server | `true` |
| `metrics.port` | Metrics server port (must match `config.metrics.port`) | `9090` |
| `metrics.serviceMonitor.enabled` | Create ServiceMonitor for Prometheus Operator | `true` |
| `metrics.serviceMonitor.interval` | Scrape interval | `30s` |
| `metrics.serviceMonitor.scrapeTimeout` | Scrape timeout | `10s` |

#### Grafana dashboard

This repo version-controls a ready-made dashboard at [`dashboards/auth-o-tron.json`](dashboards/auth-o-tron.json): an on-call overview row (scrape health, pods by version, auth request rate, failure ratio, p99 latency, provider error rate), an Authentication RED row (rate/error/latency by result, realm and pod), a Providers row (attempts by type, outcomes including timeouts, per-provider error+timeout ratio and p99 latency), an Augmenters row (attempts, error ratio and latency for the identity/role augmentation that runs in the auth path), an API RED row (HTTP request rate and p99 latency by matched route, 5xx error ratio, status-code mix, in-flight by method, and per-pod throughput), a per-pod Runtime row (CPU, resident/virtual memory, open file descriptors vs max, OS threads, uptime), and a Browser sign-in and OAuth row (OIDC provider availability, browser sign-in outcomes by method kind, refresh-token family events, and upstream offline-token refreshes and revocations of families coupled to an OIDC offline session), with deploy annotations driven by `authotron_build_info`. It is not deployed by the chart: import the JSON into Grafana manually (Dashboards > Import). Panels bind to `datasource`/`namespace`/`job` template variables, so one import serves multiple auth-o-tron environments scraped by the same Prometheus. Queries are grounded in the metrics auth-o-tron actually exposes — `auth_requests_total`, `auth_duration_seconds`, `auth_provider_attempts_total`, `auth_provider_duration_seconds`, `augmenter_attempts_total`, `augmenter_duration_seconds`, `authotron_http_requests_total`, `authotron_http_request_duration_seconds`, `authotron_http_requests_in_flight`, `authotron_build_info`, `authotron_oidc_up`, `authotron_browser_login_attempts_total`, `authotron_oauth_refresh_tokens_total`, `authotron_oauth_upstream_tokens_total`, and the Linux `process_*` collector — and label by `realm`, `provider_name`/`provider_type`, `augmenter_name`/`augmenter_type`, `result`, and `route`/`method`/`status_code`. The auth-domain panels distinguish *why* an attempt failed (bad credentials, missing header), while the API RED row catches transport/handler faults the domain metrics cannot — a 5xx spike means the service itself is failing, distinct from a 401 credential rejection. The JSON passes [`grafana/dashboard-linter`](https://github.com/grafana/dashboard-linter) with the reasoned exclusions in [`dashboards/.lint`](dashboards/.lint) (the deployment is a set of interchangeable replicas, so per-instance matchers are deliberately omitted in favour of namespace/job scoping and per-`pod` breakdowns); update it in lockstep with metric changes in new `appVersion`s.

### Application Config

The `config` section is mounted as `config.yaml` in the container. Key fields:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `config.version` | Config format version | `"2.0.0"` |
| `config.server.host` | Bind host | `"0.0.0.0"` |
| `config.server.port` | Bind port (must match `service.targetPort`) | `8080` |
| `config.metrics.enabled` | Enable metrics endpoint | `true` |
| `config.metrics.port` | Metrics port (must match `metrics.port`) | `9090` |
| `config.jwt.iss` | JWT issuer | `""` |
| `config.jwt.exp` | JWT expiry (seconds) | `3600` |
| `config.jwt.secret` | JWT signing secret | `""` |
| `config.providers` | Authentication providers | `[]` |
| `config.store.enabled` | Enable token store | `false` |

See the [Auth-O-Tron documentation](https://github.com/ecmwf/auth-o-tron/tree/main/docs) for full configuration reference.

### Login UI

ConfigV2 only (`config.version: "2.0.0"`); v1 migration defaults the UI to disabled. The ConfigMap serializes `config`; the browser-state helper validates credentials and, for a selected bundled Valkey backend, derives its URL from the dependency service helper and supplies an instance-specific key prefix.

The chart sets `config.ui: {}` so application defaults have a single source of
truth. The defaults in the table below are supplied by the application, not
duplicated in `values.yaml`.

| Parameter | Description | Default |
|-----------|-------------|---------|
| `config.ui.enabled` | Enable the branding-only preview and stylesheet | `false` |
| `config.ui.branding.application_name` | Plain-text application name | `"Auth-O-Tron"` |
| `config.ui.branding.logo_url` | Optional validated HTTPS absolute URL or root-relative path | `null` |
| `config.ui.branding.title` | Escaped plain-text title; null/blank renders `Sign in to {application_name}` | `null` |
| `config.ui.branding.description` | Escaped plain-text description; omitted when null/blank | `null` |
| `config.providers[].browser` | Optional `{label}` on `plain`/`ecmwf-api` providers enabling direct browser login; labels must be unique, absent = API-only | omitted |
| `config.ui.oidc` | OpenID Connect sign-in methods; ids, labels and the limit of 16 browser methods are shared with provider `browser` blocks, and each realm must differ from every provider realm and other `ui.oidc` realm | `[]` |
| `config.ui.browser_session` | Shared direct-login origin, expiry, bounds and backend settings (below) | omitted |

Without direct login, the page remains a **branding preview**. External identity providers are offered as OpenID Connect methods in `config.ui.oidc`; the former `config.ui.sso` links were removed and are rejected by the schema. `GET /login` and `GET /static/login.css` require no authentication and exist only when enabled, on the main application port. If ingress paths are restricted, route both paths. Existing `/` and `/authenticate` behavior is unchanged. The footer is fixed to [Powered by Auth-O-Tron](https://github.com/ecmwf/auth-o-tron).

Direct Basic (`plain`) and ECMWF API-key (`ecmwf-api`) login are opt-in per
provider via its `browser: {label: ...}` block, independent of OIDC. Any such
method requires `config.ui.browser_session` with an explicit backend and
HTTPS `public_origin`, and create a short-lived Auth-O-Tron identity-view session
after verification. Each browser-enabled provider is served at
`/login/method/<n>`, where `n` is its 0-based index among browser-enabled
providers in `config.providers` order; route those paths, `/login/account` and
`/login/logout` too. This is not an Aviso
application callback or automatic bearer-API authentication; the Auth-O-Tron
token store remains unused. Preview behavior applies only when no direct login
is configured.

OpenID Connect methods in `config.ui.oidc` also count as direct login and need
`config.ui.browser_session` with an explicit backend. Each is served at
`/login/method/<id>` and redirects back to `/login/method/<id>/callback`, which
must be routed and registered at the identity provider. Their
`client_secret_file`, like the key files of `config.oauth.upstream_token_encryption`,
must be a file inside the pod: mount a Secret with `extraVolumes` and
`extraVolumeMounts`, for example

```yaml
extraVolumes:
  - name: oidc
    secret:
      secretName: authotron-oidc # keys client-secret and upstream.key
      defaultMode: 0444 # the container runs as uid 1000 without an fsGroup
extraVolumeMounts:
  - name: oidc
    mountPath: /run/secrets/oidc
    readOnly: true
config:
  ui:
    oidc:
      - id: demo-sso
        # ...
        client_secret_file: /run/secrets/oidc/client-secret
```

The volume name `config-volume` is reserved for the chart's configuration.

OAuth refresh tokens stored in Valkey (bundled or external) also need
`config.oauth.refresh_token_retry_key_file`: 32 random bytes in standard Base64,
the same on every replica and distinct from the upstream token keys, mounted from a
Secret the same way (for example `openssl rand -base64 32` into a key `retry.key`).
Rendering fails when an enabled client has `refresh_tokens.enabled` and the file is
not set, as the server would refuse to start, unless `extraEnv` sets
`AOT_OAUTH__REFRESH_TOKEN_RETRY_KEY_FILE` to a non-empty `value` or a `valueFrom`;
the server reads that variable over the configuration. Replacing the key only makes
retries that span the change fail; see the Auth-O-Tron OAuth documentation's
*Retries*.

The page links to origin-root `/static/login.css` and `/favicon.ico` assets. Prefix-rewriting ingresses must also route those root paths; the preview has no configurable base path.

Logo and sign-in URLs must be HTTPS absolute URLs without userinfo, or root-relative paths starting with `/` but not `//`; backslashes, control characters, and whitespace are forbidden. Invalid values or schemes reject the configuration. Sign-in labels must not be blank. Destinations come only from operator configuration, not request callback/return parameters. A root-relative logo must already be served by your origin or ingress; the server does not fetch URLs or read arbitrary local files. Mounted-logo assets and color settings are not implemented.

The current default image **`0.3.6` lacks the UI endpoints**. To test, override `image.repository` and `image.tag` with an image built from `feat/login-ui-shell`. An eventual released version containing the UI is required for released deployments.

### Shared browser state (since chart 0.4.0)

The canonical chart interface is `config.ui.browser_session.backend.type`
(`valkey` or explicit development-only `memory`) plus
`browserState.passwordSecret: {name, key}` for Valkey. All non-secret runtime
settings remain under `config.ui.browser_session`. The password is injected only
as `AOT_UI__BROWSER_SESSION__BACKEND__PASSWORD` using `secretKeyRef`; the chart
does not create or look up that Secret. An empty `backend.password` placeholder
is allowed, but a non-empty password in `config`, an inline password in
`extraEnv`, URL userinfo, inline bundled ACL passwords/config, and duplicate
password environment variables are rejected without printing credentials.
Use the canonical reference for Valkey rather than adding a second password env.
External-primary deployments may instead supply exactly one password `extraEnv`
with `valueFrom.secretKeyRef` containing both `name` and `key`, while leaving
`browserState.passwordSecret.name` empty. Multiple password env entries are
rejected even when they reference the same Secret. Bundled Valkey requires the
canonical reference to validate that client and server credentials match.

`valkey.enabled` defaults to `false`; enabling it alone does **not** enable UI,
choose a backend, set the public origin, or select a provider. API-only deployments
may provision it independently. With `backend.type: valkey` and the dependency
enabled, the chart replaces `backend.url` with
`redis://<valkey.fullname>:6379/0` using the actual subchart context. This respects
release names (including names containing `valkey` or `auth-o-tron`),
`valkey.nameOverride`, `valkey.fullnameOverride`, and upstream truncation. Use
names so that the **computed bundled Valkey fullname is at most 58 characters**
(**55** when its metrics Service is enabled, to fit the `-metrics` suffix);
rendering rejects longer names to keep the upstream `-init` container suffix
within Kubernetes' 63-character limit. This applies to the release/nameOverride
combination as well as fullnameOverride, after upstream truncation.

The default `key_prefix` is `authotron:browser:<32-hex-hash>` (50 ASCII bytes).
The hash is the first 32 hex characters of SHA-256 over the compact JSON array
`[namespace, releaseName, Chart.Name, authotronFullname]`, where `Chart.Name` is
the dependency alias when aliased, and `authotronFullname` comes from the
Auth-O-Tron fullname helper. It isolates namespaces and multiple aliased chart
instances in the same release, including instances using an external primary.
It is independent of replica count, TTL and other runtime settings, and remains
below the application's 128-byte bound even for maximum-length identity inputs.
Changing namespace, release, alias or computed application fullname changes the
default state namespace and makes previous browser state inaccessible.

Rollout note: earlier chart previews used `authotron:browser:v1:<hash>`. Dropping
the `v1` segment orphans those keys, which is intended: the server's v2 browser
record namespace already ignores records written by earlier versions, so no
migration is needed. Orphaned keys expire through their TTLs.

An explicit `backend.key_prefix` is preserved as the operator's choice; it must
be 1–128 ASCII characters using only letters, digits, `:`, `_` or `-`. **Reusing
an explicit prefix across independent deployments sharing a primary/database
mixes their browser state and rate limits.** Choose a unique prefix for each
logical deployment; do not concatenate long raw namespace/release/fullname
strings that can exceed 128 bytes. Existing deployments migrating from the old
release-only default will start with fresh browser state under the new default.

With the dependency disabled, supply an explicit non-secret `backend.url` to a
**writable primary** (`redis://host:6379/0`, or `rediss://host:6379/0` when supported
by the feature build). Cluster/Sentinel discovery and replica/read endpoints are
not this interface. External service topology, TLS trust, access policy, resource
bounds and persistence belong to its operator.

Bundled Valkey is one authenticated standalone Deployment, ClusterIP port 6379,
with `Recreate` updates, bounded server and init resources, and no ingress. It is
**not HA**: outages interrupt direct login/session access. State is durable by
default: `valkey.dataStorage` creates a `ReadWriteOnce` 1Gi PersistentVolumeClaim
(`className: ""` uses the cluster default StorageClass; set `requestedSize`,
`className` and `accessModes` as needed) mounted at `/data`, and
`valkey.valkeyConfig` enables `appendonly yes` with `appendfsync everysec` and
`save ""` (AOF only, at most about one second of writes lost on a crash). OAuth
refresh tokens live only in Valkey, so keep both: a volume without AOF, or AOF on
`emptyDir`, loses them on restart. Auth-O-Tron logs
`oauth.refresh_token.store_not_durable` at startup when refresh tokens are enabled
and Valkey reports AOF off. Setting `valkey.dataStorage.enabled: false` makes state
ephemeral again. Upgrading from an ephemeral release discards existing state once.
Losing the backend clears browser sessions/forms/rate state and refresh tokens:
users sign in again. External Valkey (dependency disabled) must provide equivalent
persistence itself. Default `maxmemory 64mb` and
`maxmemory-policy noeviction` fail writes at capacity rather than evicting active
state. Keep maxmemory below the container memory limit with overhead headroom.
Tune `valkey.resources`, `valkey.initResources` and `valkey.valkeyConfig` together.
TCP health probes check listening, not authenticated command health.

The default `browserState.networkPolicy.enabled: true` permits TCP 6379 only
from the same namespace's Auth-O-Tron pods matching this chart's name and release
labels. It requires a NetworkPolicy-capable CNI. There is no namespace-wide allow
and no outbound restriction. Extra `valkey.networkPolicy` rules are rejected
while this policy is enabled because Kubernetes policies combine additively.
Disable the chart policy only when supplying equivalent operator-managed policy.
The upstream Helm auth-test pod is deliberately not admitted by this policy;
these offline contracts do not execute Helm test hooks.

Application defaults below are supplied by the **shared-browser-state feature
build**, not copied into the chart's default `config.ui: {}`. The default image
`0.3.6` does not implement this configuration or shared browser sessions.

| `config.ui.browser_session` field | Application default | Bounds/meaning |
|---|---|---|
| `public_origin` | required whenever `browser_session` is configured | HTTPS origin supplied by operator |
| `session_ttl_seconds` | `300` | Absolute expiry, 60–86400 seconds |
| `transaction_ttl_seconds` | `300` | Form transaction expiry, 30–900 seconds |
| `max_forms` / `max_sessions` | `1024` / `1024` | Each 1–100000 |
| `max_forms_per_window` / `max_logins_per_window` | `120` / `60` | Each 1–100000 |
| `rate_window_seconds` | `60` | 1–3600 seconds |
| `max_inflight_logins` | `8` | Per-pod verification concurrency, 1–256 |
| `max_shared_inflight_logins` | absent / `null` (disabled) | Optional Valkey-backed deployment-wide concurrency cap, 1–65536 |
| `verification_timeout_seconds` | `10` | 1–30 seconds |
| `backend.type` | explicit selection required | `valkey`; `memory` for single-replica development |
| `backend.url` | operator supplied externally; helper-derived bundled | Primary endpoint, no credentials/query/fragment |
| `backend.key_prefix` | chart supplies `authotron:browser:<32-hex-hash>` for Valkey | 1–128 ASCII letters/digits/colon/underscore/hyphen |
| `backend.connect_timeout_ms` | `2000` | 1–30000 milliseconds |
| `backend.operation_timeout_ms` | `1000` | 1–10000 milliseconds |

The values schema requires `public_origin` and `backend` whenever
`browser_session` is present and rejects unknown browser-session fields. Backend
variants are tag-specific: `memory` accepts only `type`; Valkey accepts the URL,
prefix, empty password placeholder and timeout settings listed above. Valkey
URL/prefix may be omitted from input only when a helper can supply them: bundled
URL and the default hashed prefix are generated before application serialization;
an external-primary URL is required by template validation. The actual password
field is supplied by the Secret environment override before runtime deserialization.

`memory` sessions require `replicaCount: 1` for static deployments, or HPA
`minReplicas: 1` and `maxReplicas: 1`; restart clears state. More application
replicas can share Valkey, but that does not make the single bundled Valkey HA.
Runtime environment overrides can bypass chart configuration checks; do not use
them to change backend type, replica assumptions or the bundled service URL.

#### Bundled Valkey with direct Basic login

This is a small demonstration profile: its `max_logins_per_window: 60` over
60 seconds is a shared admission quota, **not a capacity or throughput claim**.

Provision a Secret named `browser-state` in the release namespace out of band,
with key `default` holding a high-entropy single-line alphanumeric/base64url
password (no trailing newline or backslash; upstream init scripts hash shell-read
passwords). Do not place its value in a values file or command-line Helm option.
Both references below must match literally; templated secret names are not used.

```yaml
image:
  repository: your-registry/auth-o-tron
  tag: shared-browser-state-feature-build
replicaCount: 2
browserState:
  passwordSecret:
    name: browser-state
    key: default
valkey:
  enabled: true
  auth:
    usersExistingSecret: browser-state
    aclUsers:
      default:
        passwordKey: default
config:
  providers:
    - type: plain
      name: basic-login
      realm: browser
      users: [] # supply users from a private config source
      browser:
        label: Username and password
  ui:
    enabled: true
    browser_session:
      public_origin: https://login.example.com
      session_ttl_seconds: 600
      transaction_ttl_seconds: 120
      max_forms: 1024
      max_sessions: 1024
      max_forms_per_window: 120
      max_logins_per_window: 60
      rate_window_seconds: 60
      max_inflight_logins: 8
      verification_timeout_seconds: 10
      backend:
        type: valkey
        connect_timeout_ms: 2000
        operation_timeout_ms: 1000
```

For ECMWF direct login, add `browser: {label: ECMWF API key}` to the `ecmwf-api`
provider; neither origin nor expiry lives in the provider `browser` block. For a generic bundled Valkey without direct browser login, retain the two
Secret references and `valkey.enabled: true` but omit the `config.ui` settings.

#### External primary

Use the same feature image, direct provider, origin and expiry settings above,
but replace the dependency/backend/credential settings with:

```yaml
valkey:
  enabled: false
browserState:
  passwordSecret:
    name: external-browser-state
    key: password
config:
  ui:
    browser_session:
      backend:
        type: valkey
        url: redis://valkey-primary.internal:6379/0
        key_prefix: authotron:browser:production-gateway
        connect_timeout_ms: 2000
        operation_timeout_ms: 1000
```

When used as a parent-chart dependency, place **all** these inner values
(`image`, `config`, `valkey`, `browserState`, `replicaCount`, `resources`,
`autoscaling`) beneath the parent's
Auth-O-Tron dependency name/alias. The nested Valkey helper receives its own
subchart context; do not configure the parent's unrelated `valkey` key.

#### Dependency verification and offline checks

Pinned official chart: [`valkey` 0.12.0](https://github.com/valkey-io/valkey-helm/releases/tag/valkey-0.12.0),
repository [`https://valkey.io/valkey-helm/`](https://valkey.io/valkey-helm/index.yaml),
app/image `docker.io/valkey/valkey:9.1.2`. The vendored archive's SHA-256 matches
the public index:
`64d43433d6b80addb012dd7c21a1bf674bf034dc51210b6bf8eae9ddaf83740f`.
`Chart.lock` records both dependencies; MongoDB remains Bitnami **16.4.2**.
No Bitnami Valkey scripts or image substitution are used.

The existing offline MongoDB archive was repacked before being vendored. Its
SHA-256 is `5a4ad8f2784efb3bcc250a379e6439fcc7c8cbe8eec40da76febaadf0f8d75de`.
Independent review confirmed that its file paths and file contents match the
official Bitnami 16.4.2 package; archive directory entries and packaging differ.
It is therefore not claimed to be byte-identical to the upstream download.

Verified live on 2026-10-10: official project repository ownership and recent
maintenance, versioned Helm metadata/package, Docker Hub active image tag,
[`9.1` image Dockerfile](https://github.com/valkey-io/valkey-container/blob/mainline/9.1/debian/Dockerfile)
and [entrypoint](https://github.com/valkey-io/valkey-container/blob/mainline/docker-entrypoint.sh).
The dependency explicitly runs its own `/scripts/init.sh` in the official image
and `valkey-server /data/conf/valkey.conf`, rather than relying on the image's
`tini -- docker-entrypoint.sh` entrypoint. Secret contents are read from mounted
files; init logging reports credential source, not password values.

The chart and container packaging are BSD-3-Clause; Valkey declares BSD-3-Clause
(container OS/dependencies have their own licenses). The upstream chart archive
omits its license file, so its exact version's notice is retained separately in
[`VALKEY-LICENSE.txt`](VALKEY-LICENSE.txt). Auth-O-Tron's chart remains Apache-2.0.

Offline checks are tested with Helm 3.17.3 and 4.0.1 and Python 3.12, with the
test dependencies installed (PyYAML and Ruff):

```bash
python3 -m pip install -r tests/requirements.txt
python3 tests/render_contract.py
python3 -m ruff check tests
python3 -m ruff format --check tests
```

The suite includes strict Helm lint profiles and owns isolated, automatically
cleaned temporary Helm homes. It needs no pre-existing Helm configuration or
dependency download. CI runs the same suite and Ruff checks.

Bundled Valkey still requires its existing Secret for API-only deployments, but
the application password environment variable is injected only when
`config.ui.browser_session.backend.type: valkey` is selected. Application and
Valkey fullnames must differ: releases such as `auth-o-tron-valkey` can collide
under the existing fullname rules and are rejected. Set
`valkey.fullnameOverride: browser-state` (or another distinct name) to resolve
the collision. Guards also reject overlapping application/Valkey pod selectors
(choose distinct `nameOverride` values; fullname overrides do not affect selectors)
and application Service names matching an enabled Valkey `-metrics` Service.
Valkey `commonLabels`/`podLabels` cannot override selector labels. Valid existing
names and selectors retain their meaning.

#### Generated application config schema

`values.schema.json` `properties.config` is **generated** from the server's
`authotron/schema.json`; do not edit it (or the `definitions/authotron.*`
entries) by hand. `tools/generate_config_schema.py` converts the server's draft
2020-12 schema to the draft-07 dialect Helm 3.17 validates: `$defs` move to
root `definitions/authotron.<Name>`, refs are rewritten, and keywords next to
`$ref` are wrapped in `allOf` so they keep their 2020-12 meaning (including a
sibling `additionalProperties: false`). `deprecated` is copied as an annotation
that draft-07 ignores. Unknown keywords abort generation instead of being
silently dropped. Chart-only parts
of the file (image, replicas, autoscaling, browserState, valkey, ...) are
preserved.

Provenance is recorded in `properties.config["x-authotron-source"]`
(repository, full commit, path, SHA-256 of the schema bytes); it is the only
server pin in this chart. The default application image **0.3.6** does not
implement the pinned browser features; use an image built from the pinned
commit, or check the schema of your image source before deploying.

A few chart-owned deltas (`CHART_OVERRIDES` in the generator) are applied on
top, each asserting the server value it replaces so a server change forces a
review: the Valkey backend only requires `type` in values (the chart injects
`url` for bundled Valkey and `key_prefix`; the password comes from a Secret
env), `password` must be empty, and `key_prefix` is restricted to
`[A-Za-z0-9:_-]{1,128}`. Server-required fields such as `store`, `jwt`,
`server` and `logging` are satisfied by `values.yaml` defaults; Helm validates
the merged values, so nulling one of them is rejected.

Template `fail` checks remain only for rules JSON Schema cannot express:
unique provider `browser.id`s, unique browser labels (trimmed,
case-insensitive), at most 16 browser methods, a browser method requiring
`config.ui.browser_session.backend`, HTTPS origin/URL shapes, and topology
rules. Render tests derive numeric boundaries and the in-flight HPA default
(the server `max_inflight_logins` default/bounds) from the embedded schema.

Regenerate from committed server bytes, then review the diff. Without
`--source-commit` the checkout's `HEAD` is used and uncommitted schema edits are
refused; with `--source-commit <full SHA>` the generator reads
`git show <SHA>:authotron/schema.json` from the server repository and requires
it to be byte-identical to `--schema-path`:

```bash
python3 tools/generate_config_schema.py \
  --schema-path <server checkout>/authotron/schema.json --source-commit <full SHA>
python3 tests/test_generate_config_schema.py
python3 tests/render_contract.py
```

Drift test: CI checks out the recorded repository at the recorded commit and runs

```bash
python3 tools/generate_config_schema.py --check --schema-path <pinned>/authotron/schema.json
```

which fails if regenerating (including the SHA-256) changes a byte.

Pin order: land and publish the server schema change first, regenerate the
chart against that published commit, then bump the server's reverse chart pin
in its `.github/workflows/ci.yaml` (see its `.github/CI.md`). The recorded
commit must be fetchable from the recorded repository; CI fails rather than
substituting `main`.

Contracts cover defaults/disabled, the five-resource ingress preview, API-only
bundled Valkey, direct Basic bundled state, external primary, memory replica
rejection, duplicate password env and credential leakage rejection, all numeric
schema boundaries (derived from the generated schema), generated-schema
rejections, cross-provider browser rules, required/tag-specific fields, prefix alphabet/length,
namespace and same-parent alias isolation, stable prefixes across TTL/replica
changes, helper naming/overrides/long-name rejection, policy selectors, parent
alias scoping, HPA targets/prerequisites/replica ownership, shared-cap bounds,
vendor checksum and lock.
They render only and do not contact Kubernetes. Preview renderers that rewrite
the application Pod must copy the Secret reference explicitly for a direct-login
profile; merely inheriting chart configuration does not inject Pod environment.

### Horizontal scaling and browser verification capacity

The chart supports an optional **application-only** `autoscaling/v2`
HorizontalPodAutoscaler. With autoscaling enabled, Deployment `spec.replicas` is
omitted and `replicaCount` is ignored, so HPA owns the replica count. With it
disabled, the Deployment uses `replicaCount` as before. API-only deployments can
use CPU HPA without UI or Valkey. Direct browser sessions spanning multiple pods
require a Valkey backend; a memory backend cannot use HPA `maxReplicas > 1`.

| Parameter | Default | Validation / prerequisite |
|---|---|---|
| `resources` | `{}` | Application container requests/limits, separate from `valkey.resources` |
| `autoscaling.enabled` | `false` | Creates an HPA only when enabled |
| `autoscaling.minReplicas` | `2` | Integer ≥1 and ≤maxReplicas |
| `autoscaling.maxReplicas` | `10` | Integer ≥1 |
| `autoscaling.targetCPUUtilizationPercentage` | `70` | Integer 1–100, or `null` to disable CPU target |
| `autoscaling.targetInFlightLogins` | `null` | Optional integer 1–256, strictly below effective per-pod max_inflight_logins; requires enabled UI/direct login |

At least one target must be configured when autoscaling is enabled. CPU scaling
requires **metrics-server** (or a compatible resource metrics API) and an explicit
positive application `resources.requests.cpu`. For this target the chart accepts
decimal cores (`0.25`, `1`) or millicores (`250m`), and rejects missing/zero/invalid
requests. It does not silently choose a CPU request: this value determines what
70% utilization means. Other injected containers must have suitable CPU requests
too. CPU scaling needs neither the application metrics endpoint nor Prometheus.

#### Per-pod browser metric

`autoscaling.targetInFlightLogins` uses HPA `Pods` / `AverageValue` with the exact
metric name **`authotron_browser_logins_inflight`**. The corresponding backend
feature build must expose this unlabeled application gauge: current in-flight
direct Basic and ECMWF API-key verifications combined **on that pod**. Prometheus
scraping supplies Kubernetes `namespace` and `pod` labels; the application gauge
does not contain provider/user labels. It is not the global Valkey slot count,
session count, request rate or configured concurrency limit.

The gauge can be registered at zero even when direct login is inactive. Therefore
this HPA target requires `config.ui.enabled: true` and at least one provider in
`config.providers` with a `browser` block. UI-disabled and branding-only
configurations cannot use it; API-only CPU HPA
remains supported.

The target must be **strictly below** the effective
`config.ui.browser_session.max_inflight_logins` (application default **8** when
omitted). The gauge cannot exceed that per-pod bound, so an equal or larger
target cannot drive useful scale-up. For example, target **4** is valid with the
default cap 8, and target **32** with an explicit cap **64**. This structural
check is only a minimum: leave comfortable headroom for HPA's default **10%**
tolerance and sampling delay. A target just below the cap may still prevent
scale-up within the tolerance band; prefer a comfortably lower value such as
32/64 and tune from measurements.

This target requires both `metrics.enabled: true` and
`config.metrics.enabled: true`, with matching `metrics.port` and
`config.metrics.port`. Configure Prometheus to scrape every application pod,
through the existing ServiceMonitor or equivalent external scrape configuration.
Then provide a **Prometheus Adapter or compatible custom metrics adapter** that
exposes this series through `custom.metrics.k8s.io` for the target namespace's
Pods under the same name. An exporter or ServiceMonitor alone does not make a
metric available to HPA. The chart does not install an adapter or verify that
the external metrics APIs are healthy.

For example, the operator's Prometheus Adapter rule can map the scrape labels
to Kubernetes resources as follows (part of adapter configuration, **not**
Auth-O-Tron chart values):

```yaml
rules:
  custom:
    - seriesQuery: 'authotron_browser_logins_inflight{namespace!="",pod!=""}'
      resources:
        overrides:
          namespace:
            resource: namespace
          pod:
            resource: pod
      name:
        matches: '^authotron_browser_logins_inflight$'
        as: authotron_browser_logins_inflight
      metricsQuery: 'max by (<<.GroupBy>>) (<<.Series>>{<<.LabelMatchers>>})'
```

Keep one current value per pod; do not sum duplicated scrape targets or sum all
pods into a deployment-wide metric for this `Pods` target. Check the adapter's
namespace/Pod mapping against actual scrape labels. Set
`targetCPUUtilizationPercentage: null` for custom-only scaling without a CPU
request requirement. With both targets configured, HPA uses the largest replica
recommendation, subject to its normal missing-metric and stabilization behavior.

#### Concurrency, rate quotas and expiry

In the backend feature build implementing this interface,
`config.ui.browser_session.max_inflight_logins` is a **per-pod** admission bound
(default 8). More application pods add verification slots. Optional
`max_shared_inflight_logins` imposes a separate Valkey-backed shared cap across
pods for the logical deployment/key prefix; absent or `null` disables it. A
global cap can intentionally constrain the useful concurrency gained from HPA
and should be set according to upstream provider budgets. Configure it with a
Valkey backend. The shared `max_logins_per_window` quota remains independent of
these concurrency limits and is not multiplied by adding replicas.
Optional shared caps and shared quotas can limit admitted work and suppress the
per-pod signal before its target is reached. Scaling does not circumvent either
limit; align them with the intended capacity and provider budget.

`session_ttl_seconds` is an **absolute lifetime**, not a sliding activity expiry;
`transaction_ttl_seconds` bounds form transactions. Neither setting adds a new
verification budget or resets a shared rate quota on browser activity. Keep
expiry, state capacity, provider deadlines, per-pod slots, optional shared cap
and rate limits aligned. Existing secret wiring, hashed state namespaces and
ephemeral-backend logout behavior continue to apply.

#### Illustrative production tuning profile

Merge this into the earlier direct-login profile using a feature image that
implements the per-pod limit, optional shared cap and gauge. Keep the existing
Valkey/Secret references, provider selection and HTTPS origin. This is a tuning
starting point, **not evidence that the system can serve 10000 requests/minute**:

```yaml
resources:
  requests:
    cpu: 500m
    memory: 256Mi
  limits:
    cpu: "2"
    memory: 512Mi
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
  targetInFlightLogins: null # Set e.g. 32 only after the custom adapter is ready.
config:
  ui:
    browser_session:
      max_inflight_logins: 64
      max_shared_inflight_logins: null # No optional deployment-wide cap.
      max_logins_per_window: 10000
      rate_window_seconds: 60
```

The quota of 10000/minute permits attempts; it does not prove throughput. Measure
verification latency, admission rejection rates, CPU/memory, provider throttling,
adapter freshness and Valkey load before choosing targets. I/O-bound verification
may saturate slots without high CPU, making the per-pod gauge useful once its
adapter is available. HPA reacts after load appears and cannot replace admission
limits or provider capacity planning.

Two or more application replicas provide horizontal application capacity, but
**the single bundled Valkey remains one non-HA backend**. Application HPA neither
scales it nor removes its outage/restart exposure. Backend HA, persistence,
failover to a writable primary and capacity planning are separate operator work.
The default application image `0.3.6` lacks the shared-browser-state settings and
gauge; do not use it for this direct-login/custom-metric profile. No 10000-request
benchmark or cluster scaling exercise is performed by the offline chart tests.

### Other

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Static replicas; ignored with HPA enabled | `1` |
| `podAnnotations` | Pod annotations | `{}` |
| `extraEnv` | Extra environment variables (for secrets via `secretKeyRef`) | `[]` |
| `mongodb.enabled` | Deploy MongoDB subchart | `false` |
| `pullSecret.enabled` | Create image pull secret | `false` |

## Examples

### Minimal deployment

```yaml
config:
  jwt:
    iss: my-org
    exp: 3600
    secret: changeme
  providers:
    - type: plain
      name: default
      realm: default
      users:
        - username: admin
          password: changeme
```

### With ingress and TLS

```yaml
ingress:
  enabled: true
  className: nginx
  hosts:
    - host: auth.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: auth-tls
      hosts:
        - auth.example.com
```

### Aviso-branded login preview

Use these values with a feature-branch image (replace the illustrative image repository and tag with your built image):

```yaml
image:
  repository: your-registry/auth-o-tron
  tag: login-ui-shell
config:
  version: "2.0.0"
  ui:
    enabled: true
    branding:
      application_name: "Aviso"
      logo_url: null
      title: null
      description: "Aviso sign-in preview"
```

When using this chart as a subchart, place the values above under `<dependency-name-or-alias>` in the parent's values file: use the dependency's `alias` from the parent's `Chart.yaml` if set, otherwise its dependency `name`. Put both `image` and `config` inside that key; the example above shows the inner values, not the parent wrapper.

Environment overrides also work through `extraEnv`, including `AOT_UI__ENABLED` and `AOT_UI__BRANDING__APPLICATION_NAME`.

### Passing secrets via environment

```yaml
extraEnv:
  - name: AOT_JWT__SECRET
    valueFrom:
      secretKeyRef:
        name: auth-o-tron-secrets
        key: jwt-secret
```

## License

[Apache-2.0](LICENSE.txt)
