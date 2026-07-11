![Auth-O-Tron](https://raw.githubusercontent.com/ecmwf/auth-o-tron/main/authotron/docs/logo-light.png)

<div align="center">

[![ECMWF](https://github.com/ecmwf/codex/raw/refs/heads/main/ESEE/foundation_badge.svg)](https://github.com/ecmwf/codex/raw/refs/heads/main/ESEE)
[![Maturity](https://github.com/ecmwf/codex/raw/refs/heads/main/Project%20Maturity/emerging_badge.svg)](https://github.com/ecmwf/codex/raw/refs/heads/main/Project%20Maturity)

</div>

# Auth-O-Tron Helm Chart

Helm chart for deploying [Auth-O-Tron](https://github.com/ecmwf/auth-o-tron) on Kubernetes, an authentication and authorization gateway for web APIs.

## Installation

```bash
kubectl create secret generic auth-o-tron-jwt \
  --from-file=private-key.pem=jwt-private.pem
helm install auth-o-tron ./auth-o-tron-chart \
  --set-string config.jwt.iss=https://auth.example.com \
  --set-string config.jwt.kid=key-2026-01
```

Chart 0.4.0 explicitly targets the pending Auth-O-Tron 0.4.0 package/container from [auth-o-tron#84](https://github.com/ecmwf/auth-o-tron/pull/84) at upstream SHA `5ad7682aaf21a4de741ca4f64c49669b89032e54`, together with the token-store removal in [auth-o-tron#80](https://github.com/ecmwf/auth-o-tron/pull/80). The default image will not be usable until that 0.4.0 image is published. Dashboard metric migration remains coordinated separately in [chart#12](https://github.com/ecmwf/auth-o-tron-chart/pull/12).

## Configuration

All configuration is done through `values.yaml`. See below for key settings.

### Image

| Parameter | Description | Default |
| ----------- | ------------- | --------- |
| `image.repository` | Container image repository | `eccr.ecmwf.int/auth-o-tron/auth-o-tron` |
| `image.tag` | Image tag | `0.4.0` |
| `image.pullPolicy` | Pull policy | `IfNotPresent` |

### Service

| Parameter | Description | Default |
| ----------- | ------------- | --------- |
| `service.type` | Service type | `ClusterIP` |
| `service.port` | Client-facing port | `8080` |
| `service.targetPort` | Container listen port (must match `config.server.port`) | `8080` |
| `service.annotations` | Service annotations | `{}` |

### Ingress

| Parameter | Description | Default |
| ----------- | ------------- | --------- |
| `ingress.enabled` | Enable Ingress resource | `false` |
| `ingress.className` | Ingress class name | `""` |
| `ingress.annotations` | Ingress annotations | `{}` |
| `ingress.hosts` | Ingress host rules | `[{host: auth-o-tron.local, paths: [{path: /, pathType: Prefix}]}]` |
| `ingress.tls` | TLS configuration | `[]` |

Only the application port is routed via Ingress. The metrics port is not included in the Ingress rules. In production, enable TLS and consider restricting ingress paths to only the endpoints you need exposed (e.g. `/authenticate`, `/health`).

### Metrics

| Parameter | Description | Default |
| ----------- | ------------- | --------- |
| `metrics.enabled` | Enable dedicated metrics server | `true` |
| `metrics.port` | Metrics server port (must match `config.metrics.port`) | `9090` |
| `metrics.serviceMonitor.enabled` | Create ServiceMonitor for Prometheus Operator | `true` |
| `metrics.serviceMonitor.interval` | Scrape interval | `30s` |
| `metrics.serviceMonitor.scrapeTimeout` | Scrape timeout | `10s` |

#### Grafana dashboard

This repo version-controls a ready-made dashboard at [`dashboards/auth-o-tron.json`](dashboards/auth-o-tron.json): an on-call overview row (scrape health, pods by version, auth request rate, failure ratio, p99 latency, provider error rate), an Authentication RED row (rate/error/latency by result, realm and pod), a Providers row (attempts by type, outcomes including timeouts, per-provider error+timeout ratio and p99 latency), an Augmenters row (attempts, error ratio and latency for the identity/role augmentation that runs in the auth path), an API RED row (HTTP request rate and p99 latency by matched route, 5xx error ratio, status-code mix, in-flight by method, and per-pod throughput), and a per-pod Runtime row (CPU, resident/virtual memory, open file descriptors vs max, OS threads, uptime), with deploy annotations driven by `authotron_build_info`. It is not deployed by the chart: import the JSON into Grafana manually (Dashboards > Import). Panels bind to `datasource`/`namespace`/`job` template variables, so one import serves multiple auth-o-tron environments scraped by the same Prometheus. Queries are grounded in the metrics auth-o-tron actually exposes — `auth_requests_total`, `auth_duration_seconds`, `auth_provider_attempts_total`, `auth_provider_duration_seconds`, `augmenter_attempts_total`, `augmenter_duration_seconds`, `authotron_http_requests_total`, `authotron_http_request_duration_seconds`, `authotron_http_requests_in_flight`, `authotron_build_info`, and the Linux `process_*` collector — and label by `realm`, `provider_name`/`provider_type`, `augmenter_name`/`augmenter_type`, `result`, and `route`/`method`/`status_code`. The auth-domain panels distinguish *why* an attempt failed (bad credentials, missing header), while the API RED row catches transport/handler faults the domain metrics cannot — a 5xx spike means the service itself is failing, distinct from a 401 credential rejection. The JSON passes [`grafana/dashboard-linter`](https://github.com/grafana/dashboard-linter) with the reasoned exclusions in [`dashboards/.lint`](dashboards/.lint) (the deployment is a set of interchangeable replicas, so per-instance matchers are deliberately omitted in favour of namespace/job scoping and per-`pod` breakdowns); update it in lockstep with metric changes in new `appVersion`s.

### Application Config

The `config` section is mounted as `config.yaml` in the container. Key fields:

| Parameter | Description | Default |
| ----------- | ------------- | --------- |
| `config.version` | Config format version | `"2.0.0"` |
| `config.server.host` | Bind host | `"0.0.0.0"` |
| `config.server.port` | Bind port (must match `service.targetPort`) | `8080` |
| `config.metrics.enabled` | Enable metrics endpoint | `true` |
| `config.metrics.port` | Metrics port (must match `metrics.port`) | `9090` |
| `config.jwt.iss` | Required exact JWT issuer | `""` (must override) |
| `config.jwt.aud` | Exact JWT audience | `polytope-server` |
| `config.jwt.kid` | Required active signing-key identifier | `""` (must override) |
| `config.jwt.exp` | JWT expiry (seconds) | `3600` |
| `jwt.privateKeySecret.name` | Existing Secret containing the private PEM | `auth-o-tron-jwt` |
| `jwt.privateKeySecret.key` | Key in that Secret | `private-key.pem` |
| `config.providers` | Authentication providers | `[]` |

See the [Auth-O-Tron documentation](https://github.com/ecmwf/auth-o-tron/tree/main/authotron/docs) for full configuration reference.

### Other

| Parameter | Description | Default |
| ----------- | ------------- | --------- |
| `replicaCount` | Number of replicas | `1` |
| `podAnnotations` | Pod annotations | `{}` |
| `extraEnv` | Extra environment variables (`AOT_JWT__PRIVATE_KEY` is reserved) | `[]` |
| `pullSecret.enabled` | Create image pull secret | `false` |

## Examples

### Minimal deployment

Create the signing Secret first; the chart references it but does not create or own it. The value must be a complete RSA private PEM of at least 2048 bits; 3072 bits is recommended:

```bash
kubectl create secret generic auth-o-tron-jwt \
  --from-file=private-key.pem=jwt-private.pem
```

```yaml
config:
  jwt:
    iss: https://auth.example.com
    aud: polytope-server
    exp: 3600
    kid: key-2026-01
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

### Referencing a different signing Secret

```yaml
jwt:
  privateKeySecret:
    name: auth-o-tron-jwt-key-2026-02
    key: signing.pem
```

The Secret must already exist in the release namespace. `config.jwt.secret`, `config.jwt.private_key`, and an `AOT_JWT__PRIVATE_KEY` entry in `extraEnv` are rejected so private key material cannot enter the rendered ConfigMap or bypass this reference.

## Upgrading to Auth-O-Tron 0.4

Auth-O-Tron 0.4 replaces HMAC signing with RS256. Before upgrading the signer, deploy consumers using `authotron-client` 0.2.0 with the exact configured issuer and `polytope-server` audience, and publish the new public key under the configured `kid`. The initial HMAC-to-RSA migration cannot accept both algorithms and may cause a brief authentication interruption if consumers and signer cannot be switched atomically.

For later RSA key rotations, keep the old public key in every consumer, add the new public key and `kid`, then update `config.jwt.kid` and `jwt.privateKeySecret` together. The values checksum triggers a signer rollout when either reference or `kid` changes. Wait at least `config.jwt.exp` plus verifier clock skew before removing the old public key. The signer chart needs only the active private key and `kid`; overlapping public keysets remain consumer-owned.

The chart never owns or renders the private PEM. Updating data in an existing Secret does not by itself restart pods; use a versioned Secret reference with the new `kid` (recommended), run a Helm upgrade that changes the `kid`, or explicitly restart the Deployment. Never reuse a `kid` for different key material.

## License

[Apache-2.0](LICENSE.txt)
