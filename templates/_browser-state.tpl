{{/* Hash a stable instance identity, independent of runtime limits and replicas. */}}
{{- define "authotron.browserKeyPrefix" -}}
{{- $identity := list .Release.Namespace .Release.Name .Chart.Name (include "fullname" .) -}}
{{- printf "authotron:browser:v1:%s" ($identity | toJson | sha256sum | trunc 32) -}}
{{- end -}}

{{/* Validate before serialization; error messages never interpolate credentials. */}}
{{- define "authotron.browserConfig" -}}
{{- $config := deepCopy .Values.config -}}
{{- $ui := default dict $config.ui -}}
{{- $session := default dict $ui.browser_session -}}
{{- $backend := default dict $session.backend -}}
{{- $secret := .Values.browserState.passwordSecret -}}
{{- if and (hasKey $ui "browser_session") (not (regexMatch "^https://[^/@?#\\\\[:space:][:cntrl:]]+/?$" (default "" $session.public_origin))) -}}
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
{{- if and (or $ui.ecmwf_api_key $ui.basic) (not $backend.type) -}}
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
  {{- if and $v.metrics.enabled $v.metrics.service.enabled (eq $appFullname (printf "%s-metrics" $valkeyFullname)) -}}
    {{- fail "application Service name collides with bundled Valkey metrics Service name; set fullnameOverride or valkey.fullnameOverride to distinct resource names" -}}
  {{- end -}}
  {{- if and $v.metrics.enabled $v.metrics.service.enabled (gt (len $valkeyFullname) 55) -}}
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
