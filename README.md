![Auth-O-Tron](https://raw.githubusercontent.com/ecmwf/auth-o-tron/main/docs/logo-light.png)

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

Only the application port is exposed via ingress. The metrics port stays internal to the cluster. In production, enable TLS and consider restricting ingress paths to only the endpoints you need exposed (e.g. `/authenticate`, `/health`).

### Metrics

| Parameter | Description | Default |
|-----------|-------------|---------|
| `metrics.enabled` | Enable dedicated metrics server | `true` |
| `metrics.port` | Metrics server port (must match `config.metrics.port`) | `9090` |
| `metrics.serviceMonitor.enabled` | Create ServiceMonitor for Prometheus Operator | `true` |
| `metrics.serviceMonitor.interval` | Scrape interval | `30s` |
| `metrics.serviceMonitor.scrapeTimeout` | Scrape timeout | `10s` |

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