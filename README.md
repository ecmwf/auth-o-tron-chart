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
| `image.tag` | Image tag | `0.3.1` |
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

This repo version-controls a ready-made dashboard at [`dashboards/auth-o-tron.json`](dashboards/auth-o-tron.json): an on-call overview row (scrape health, pods by version, auth request rate, failure ratio, p99 latency, provider error rate), an Authentication RED row (rate/error/latency by result, realm and pod), a Providers row (attempts by type, outcomes including timeouts, per-provider error+timeout ratio and p99 latency), an Augmenters row (attempts, error ratio and latency for the identity/role augmentation that runs in the auth path), an API RED row (HTTP request rate and p99 latency by matched route, 5xx error ratio, status-code mix, in-flight by method, and per-pod throughput), and a per-pod Runtime row (CPU, resident/virtual memory, open file descriptors vs max, OS threads, uptime), with deploy annotations driven by `authotron_build_info`. It is not deployed by the chart: import the JSON into Grafana manually (Dashboards > Import). Panels bind to `datasource`/`namespace`/`job` template variables, so one import serves multiple auth-o-tron environments scraped by the same Prometheus. Queries are grounded in the metrics auth-o-tron actually exposes — `auth_requests_total`, `auth_duration_seconds`, `auth_provider_attempts_total`, `auth_provider_duration_seconds`, `augmenter_attempts_total`, `augmenter_duration_seconds`, `authotron_http_requests_total`, `authotron_http_request_duration_seconds`, `authotron_http_requests_in_flight`, `authotron_build_info`, and the Linux `process_*` collector — and label by `realm`, `provider_name`/`provider_type`, `augmenter_name`/`augmenter_type`, `result`, and `route`/`method`/`status_code`. The auth-domain panels distinguish *why* an attempt failed (bad credentials, missing header), while the API RED row catches transport/handler faults the domain metrics cannot — a 5xx spike means the service itself is failing, distinct from a 401 credential rejection. The JSON passes [`grafana/dashboard-linter`](https://github.com/grafana/dashboard-linter) with the reasoned exclusions in [`dashboards/.lint`](dashboards/.lint) (the deployment is a set of interchangeable replicas, so per-instance matchers are deliberately omitted in favour of namespace/job scoping and per-`pod` breakdowns); update it in lockstep with metric changes in new `appVersion`s.

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

### Other

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of replicas | `1` |
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