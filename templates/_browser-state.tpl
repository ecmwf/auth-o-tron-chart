{{/* Hash a stable instance identity, independent of runtime limits and replicas. */}}
{{- define "authotron.browserKeyPrefix" -}}
{{- $identity := list .Release.Namespace .Release.Name .Chart.Name (include "fullname" .) -}}
{{- printf "authotron:browser:%s" ($identity | toJson | sha256sum | trunc 32) -}}
{{- end -}}

{{/* Render "true" when any provider has a non-null browser map (`browser: null` means
API-only) or config.ui.oidc lists an OIDC sign-in method. */}}
{{- define "authotron.hasBrowserMethod" -}}
{{- range (default list .Values.config.providers) -}}
{{- if and (kindIs "map" .) (kindIs "map" .browser) -}}true{{- end -}}
{{- end -}}
{{- if (default dict .Values.config.ui).oidc -}}true{{- end -}}
{{- end -}}

{{/* Validate before serialization; error messages never interpolate credentials. */}}
{{- define "authotron.browserConfig" -}}
{{- $config := deepCopy .Values.config -}}
{{- $ui := default dict $config.ui -}}
{{- $session := default dict $ui.browser_session -}}
{{- $backend := default dict $session.backend -}}
{{- $secret := .Values.browserState.passwordSecret -}}
{{- if and $ui.browser_session (not (regexMatch "^https://[^/@?#\\\\[:space:][:cntrl:]]+/?$" (default "" $session.public_origin))) -}}
  {{- fail "browser sessions require public_origin as an absolute HTTPS origin without credentials, path, query or fragment" -}}
{{- end -}}
{{- if $backend.password -}}
  {{- fail "browser backend password must use browserState.passwordSecret, never config" -}}
{{- end -}}
{{- if and $backend.url (not (regexMatch "^rediss?://[^/@?#[:space:]]+(/[0-9]+)?$" $backend.url)) -}}
  {{- fail "browser backend URL must be a primary redis:// or rediss:// endpoint without userinfo/query/fragment" -}}
{{- end -}}
{{- $passwordEnvs := 0 -}}
{{- range .Values.extraEnv -}}
  {{- if eq .name "AOT_UI__BROWSER_SESSION__BACKEND__PASSWORD" -}}
    {{- $passwordEnvs = add1 $passwordEnvs -}}
    {{- if or $secret.name (not (dig "valueFrom" "secretKeyRef" "name" "" .)) (not (dig "valueFrom" "secretKeyRef" "key" "" .)) (hasKey . "value") -}}
      {{- fail "browser password extraEnv must be secretKeyRef only, and cannot duplicate browserState.passwordSecret" -}}
    {{- end -}}
  {{- end -}}
  {{- if eq .name "AOT_UI__BROWSER_SESSION__BACKEND__URL" -}}
    {{- fail "set browser backend URL in config, not extraEnv" -}}
  {{- end -}}
{{- end -}}
{{- if gt (int $passwordEnvs) 1 -}}
  {{- fail "browser password extraEnv must contain at most one secretKeyRef entry" -}}
{{- end -}}
{{/* Cross-method rules JSON Schema cannot express; per-field shape is schema-validated.
Provider browser blocks and config.ui.oidc methods share ids, labels and the limit of 16.
An OIDC realm must differ from every provider realm and from the other OIDC realms. */}}
{{- $methodSpecs := list -}}
{{- $realms := dict -}}
{{- range (default list $config.providers) -}}
  {{- if kindIs "map" . -}}
    {{- if kindIs "map" .browser -}}{{- $methodSpecs = append $methodSpecs .browser -}}{{- end -}}
    {{- if hasKey . "realm" -}}{{- $_ := set $realms (toString .realm) true -}}{{- end -}}
  {{- end -}}
{{- end -}}
{{- range (default list $ui.oidc) -}}
  {{- if kindIs "map" . -}}
    {{- $methodSpecs = append $methodSpecs . -}}
    {{- $realm := toString .realm -}}
    {{- if hasKey $realms $realm -}}{{- fail (printf "ui.oidc realm %q must differ from every provider realm and other ui.oidc realm" $realm) -}}{{- end -}}
    {{- $_ := set $realms $realm true -}}
  {{- end -}}
{{- end -}}
{{- $ids := dict -}}
{{- $labels := dict -}}
{{- range $methodSpecs -}}
  {{- if hasKey . "id" -}}
    {{- $id := toString .id -}}
    {{- if hasKey $ids $id -}}{{- fail (printf "browser method id %q must be unique across provider browser blocks and ui.oidc" $id) -}}{{- end -}}
    {{- $_ := set $ids $id true -}}
  {{- end -}}
  {{- $label := default "" .label | toString | trim | lower -}}
  {{- if hasKey $labels $label -}}{{- fail "browser method labels must be unique (case-insensitive, trimmed)" -}}{{- end -}}
  {{- $_ := set $labels $label true -}}
{{- end -}}
{{- if gt (len $methodSpecs) 16 -}}
  {{- fail "at most 16 browser methods (provider browser blocks and ui.oidc entries) are allowed" -}}
{{- end -}}
{{- if and (include "authotron.hasBrowserMethod" .) (not $backend.type) -}}
  {{- fail "direct browser login requires config.ui.browser_session.backend.type" -}}
{{- end -}}
{{- if and (eq $backend.type "memory") (not .Values.autoscaling.enabled) (gt (int .Values.replicaCount) 1) -}}
  {{- fail "memory browser sessions require replicaCount: 1; use valkey for shared state" -}}
{{- end -}}
{{- if and (eq $backend.type "memory") .Values.autoscaling.enabled (gt (int .Values.autoscaling.maxReplicas) 1) -}}
  {{- fail "memory browser sessions require autoscaling.maxReplicas: 1; use valkey for shared state" -}}
{{- end -}}
{{- if .Values.valkey.enabled -}}
  {{- $v := .Subcharts.valkey.Values -}}
  {{- $appFullname := include "fullname" . -}}
  {{- $valkeyFullname := include "valkey.fullname" .Subcharts.valkey -}}
  {{- if eq $appFullname $valkeyFullname -}}
    {{- fail "application and bundled Valkey fullnames must differ; set valkey.fullnameOverride to a distinct name" -}}
  {{- end -}}
  {{/* Both selectors use the same release instance; their effective names must differ. */}}
  {{- if eq (include "name" .) (include "valkey.name" .Subcharts.valkey) -}}
    {{- fail "application and bundled Valkey pod selectors must differ; set nameOverride or valkey.nameOverride to distinct names (fullnameOverride does not change selectors)" -}}
  {{- end -}}
  {{- $selector := include "valkey.selectorLabels" .Subcharts.valkey | fromYaml -}}
  {{- range $labels := list $v.commonLabels $v.podLabels -}}
    {{- range $key, $value := $selector -}}
      {{- if and (hasKey $labels $key) (ne (index $labels $key) $value) -}}
        {{- fail "bundled Valkey commonLabels and podLabels must not override selector labels" -}}
      {{- end -}}
    {{- end -}}
  {{- end -}}
  {{- $metricsService := and $v.metrics.enabled $v.metrics.service.enabled -}}
  {{- if and $metricsService (eq $appFullname (printf "%s-metrics" $valkeyFullname)) -}}
    {{- fail "application Service name collides with bundled Valkey metrics Service name; set fullnameOverride or valkey.fullnameOverride to distinct resource names" -}}
  {{- end -}}
  {{- if and $metricsService (gt (len $valkeyFullname) 55) -}}
    {{- fail "bundled Valkey fullname must be at most 55 characters with its metrics Service enabled to fit the upstream -metrics suffix" -}}
  {{- end -}}
  {{- if ne $v.deploymentStrategy "Recreate" -}}
    {{- fail "bundled standalone Valkey requires deploymentStrategy: Recreate to avoid independent primaries behind one Service" -}}
  {{- end -}}
  {{- if gt (len $valkeyFullname) 58 -}}
    {{- fail "bundled Valkey fullname must be at most 58 characters to fit the upstream -init container suffix; shorten the release/name override" -}}
  {{- end -}}
  {{- if or $v.replica.enabled (ne $v.service.type "ClusterIP") (ne (int $v.service.port) 6379) $v.tls.enabled -}}
    {{- fail "bundled Valkey requires standalone ClusterIP port 6379 without TLS; use an external primary for other topologies" -}}
  {{- end -}}
  {{- if or (not $v.auth.enabled) (not $v.auth.usersExistingSecret) $v.auth.aclConfig -}}
    {{- fail "bundled Valkey requires auth.enabled and auth.usersExistingSecret, without inline ACL config" -}}
  {{- end -}}
  {{- range $v.auth.aclUsers -}}
    {{- if .password -}}{{- fail "bundled Valkey passwords must be in an existing Secret" -}}{{- end -}}
  {{- end -}}
  {{- $defaultUser := default dict $v.auth.aclUsers.default -}}
  {{- if or (ne $secret.name $v.auth.usersExistingSecret) (ne $secret.key (default "default" $defaultUser.passwordKey)) -}}
    {{- fail "browserState.passwordSecret must match bundled Valkey usersExistingSecret/default passwordKey exactly (literal names)" -}}
  {{- end -}}
  {{- if and .Values.browserState.networkPolicy.enabled $v.networkPolicy -}}
    {{- fail "use browserState.networkPolicy only; extra Valkey policies could widen access" -}}
  {{- end -}}
  {{- if eq $backend.type "valkey" -}}
    {{- $_ := set $backend "url" (printf "redis://%s:6379/0" (include "valkey.fullname" .Subcharts.valkey)) -}}
  {{- end -}}
{{- end -}}
{{- if eq $backend.type "valkey" -}}
  {{- if not $backend.url -}}{{- fail "external Valkey requires config.ui.browser_session.backend.url" -}}{{- end -}}
  {{/* Refresh tokens in Valkey need a retry key the same on every replica; the server
  refuses to start without it, so refuse to render. */}}
  {{- $oauth := default dict $config.oauth -}}
  {{- $refresh := false -}}
  {{- range (default list $oauth.clients) -}}
    {{- if and (kindIs "map" .) (dig "refresh_tokens" "enabled" false .) -}}{{- $refresh = true -}}{{- end -}}
  {{- end -}}
  {{- if and $oauth.enabled $refresh (not $oauth.refresh_token_retry_key_file) -}}
    {{- fail "refresh tokens in Valkey require config.oauth.refresh_token_retry_key_file, a key file mounted from a Secret on every replica" -}}
  {{- end -}}
  {{- if not (or $secret.name (eq (int $passwordEnvs) 1)) -}}{{- fail "Valkey browser sessions require browserState.passwordSecret.name or one password extraEnv secretKeyRef" -}}{{- end -}}
  {{- if not (hasKey $backend "key_prefix") -}}
    {{- $_ := set $backend "key_prefix" (include "authotron.browserKeyPrefix" .) -}}
  {{- end -}}
  {{- $_ := set $session "backend" $backend -}}
  {{- $_ := set $ui "browser_session" $session -}}
  {{- $_ := set $config "ui" $ui -}}
{{- end -}}
{{- toYaml $config -}}
{{- end -}}
