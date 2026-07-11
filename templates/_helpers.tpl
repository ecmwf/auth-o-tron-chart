{{- define "name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end -}}

{{- define "fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end -}}

{{/* Render application config after rejecting legacy or inline private-key material. */}}
{{- define "auth-o-tron.renderConfig" -}}
{{- $jwt := default dict .Values.config.jwt -}}
{{- if hasKey $jwt "secret" -}}
{{- fail "config.jwt.secret was removed in Auth-O-Tron 0.4.0; configure jwt.privateKeySecret instead" -}}
{{- end -}}
{{- if hasKey $jwt "private_key" -}}
{{- fail "config.jwt.private_key must not be stored in chart values or the ConfigMap; configure jwt.privateKeySecret instead" -}}
{{- end -}}
{{- $config := deepCopy .Values.config -}}
{{- $renderedJwt := deepCopy $jwt -}}
{{- $_ := set $renderedJwt "iss" (required "config.jwt.iss is required" $jwt.iss) -}}
{{- $_ := set $renderedJwt "aud" (required "config.jwt.aud is required" $jwt.aud) -}}
{{- $_ := set $renderedJwt "kid" (required "config.jwt.kid is required" $jwt.kid) -}}
{{- $_ := set $config "jwt" $renderedJwt -}}
{{- $config | toYaml -}}
{{- end -}}

{{- define "auth-o-tron.jwtPrivateKeySecretName" -}}
{{- required "jwt.privateKeySecret.name is required" .Values.jwt.privateKeySecret.name -}}
{{- end -}}

{{- define "auth-o-tron.jwtPrivateKeySecretKey" -}}
{{- required "jwt.privateKeySecret.key is required" .Values.jwt.privateKeySecret.key -}}
{{- end -}}

{{- define "auth-o-tron.podAnnotations" -}}
{{- $annotations := deepCopy (default dict .Values.podAnnotations) -}}
{{- $_ := set $annotations "checksum/config" (.Values | toYaml | sha256sum) -}}
{{- $annotations | toYaml -}}
{{- end -}}

{{- define "auth-o-tron.imagePullSecrets" -}}
{{- if .Values.pullSecret.enabled -}}
{{- list (dict "name" (printf "%s-pull-secret" (include "fullname" .))) | toJson -}}
{{- else -}}
[]
{{- end -}}
{{- end -}}

{{- define "auth-o-tron.containerPorts" -}}
{{- $ports := list (dict "name" "http-auth" "containerPort" .Values.service.targetPort "protocol" "TCP") -}}
{{- if .Values.metrics.enabled -}}
{{- $ports = append $ports (dict "name" "http-metrics" "containerPort" .Values.metrics.port "protocol" "TCP") -}}
{{- end -}}
{{- $ports | toYaml -}}
{{- end -}}

{{- define "auth-o-tron.environment" -}}
{{- range .Values.extraEnv -}}
{{- if eq (default "" .name) "AOT_JWT__PRIVATE_KEY" -}}
{{- fail "extraEnv must not define AOT_JWT__PRIVATE_KEY; configure jwt.privateKeySecret instead" -}}
{{- end -}}
{{- end -}}
{{- $secretRef := dict "name" (include "auth-o-tron.jwtPrivateKeySecretName" .) "key" (include "auth-o-tron.jwtPrivateKeySecretKey" .) -}}
{{- $privateKeyEnv := dict "name" "AOT_JWT__PRIVATE_KEY" "valueFrom" (dict "secretKeyRef" $secretRef) -}}
{{- concat (list $privateKeyEnv) (default (list) .Values.extraEnv) | toYaml -}}
{{- end -}}
