{{- define "adcs.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "adcs.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := include "adcs.name" . -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "adcs.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "adcs.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: adcs
{{- end -}}

{{- define "adcs.selectorLabels" -}}
app.kubernetes.io/name: {{ include "adcs.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "adcs.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "adcs.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "adcs.commonEnv" -}}
- name: ADCS_ENV
  value: {{ .Values.global.env.ADCS_ENV | quote }}
- name: ADCS_LOG_LEVEL
  value: {{ .Values.global.env.ADCS_LOG_LEVEL | quote }}
- name: ADCS_HOST
  value: {{ .Values.global.env.ADCS_HOST | quote }}
- name: ADCS_PORT
  value: {{ .Values.global.env.ADCS_PORT | quote }}
- name: ADCS_ADMIN_KEYS_SOURCE
  value: {{ .Values.global.env.ADCS_ADMIN_KEYS_SOURCE | quote }}
- name: ADCS_ADMIN_KEYS_JSON_PATH
  value: {{ .Values.global.configPaths.ADCS_ADMIN_KEYS_JSON_PATH | quote }}
- name: POSTGRES_DSN
  valueFrom:
    secretKeyRef:
      name: {{ include "adcs.fullname" . }}-secrets
      key: POSTGRES_DSN
- name: REDIS_URL
  value: {{ .Values.global.externalServices.REDIS_URL | quote }}
- name: RABBITMQ_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "adcs.fullname" . }}-secrets
      key: RABBITMQ_URL
- name: QDRANT_URL
  value: {{ .Values.global.externalServices.QDRANT_URL | quote }}
- name: OPENSEARCH_URL
  value: {{ .Values.global.externalServices.OPENSEARCH_URL | quote }}
- name: ADCS_PERSISTENCE_BACKEND
  value: {{ .Values.global.env.ADCS_PERSISTENCE_BACKEND | quote }}
- name: ADCS_RETRIEVAL_BACKEND
  value: {{ .Values.global.env.ADCS_RETRIEVAL_BACKEND | quote }}
- name: ADCS_TEST_MODE
  value: {{ .Values.global.env.ADCS_TEST_MODE | quote }}
- name: ADCS_WEBMCP_ENABLED
  value: {{ .Values.global.env.ADCS_WEBMCP_ENABLED | quote }}
- name: ADCS_WEBMCP_CONFIRM_TTL_SECONDS
  value: {{ .Values.global.env.ADCS_WEBMCP_CONFIRM_TTL_SECONDS | quote }}
- name: ADCS_MCP_SUPPORTED_REVISIONS
  value: {{ .Values.global.env.ADCS_MCP_SUPPORTED_REVISIONS | quote }}
- name: ADCS_ABUSE_GUARD_MODE
  value: {{ .Values.global.env.ADCS_ABUSE_GUARD_MODE | quote }}
- name: ADCS_ABUSE_GUARD_ALLOWLIST
  value: {{ .Values.global.env.ADCS_ABUSE_GUARD_ALLOWLIST | quote }}
- name: ADCS_ABUSE_REQUESTS_PER_IP_PER_MINUTE
  value: {{ .Values.global.env.ADCS_ABUSE_REQUESTS_PER_IP_PER_MINUTE | quote }}
- name: ADCS_ABUSE_REQUESTS_PER_FINGERPRINT_PER_MINUTE
  value: {{ .Values.global.env.ADCS_ABUSE_REQUESTS_PER_FINGERPRINT_PER_MINUTE | quote }}
- name: ADCS_ABUSE_REQUESTS_GLOBAL_PER_MINUTE
  value: {{ .Values.global.env.ADCS_ABUSE_REQUESTS_GLOBAL_PER_MINUTE | quote }}
- name: ADCS_INGESTION_PARTIAL_PUBLISH_THRESHOLD_PCT
  value: {{ .Values.global.env.ADCS_INGESTION_PARTIAL_PUBLISH_THRESHOLD_PCT | quote }}
- name: ADCS_INGESTION_METADATA_QUARANTINE_POLICY
  value: {{ .Values.global.env.ADCS_INGESTION_METADATA_QUARANTINE_POLICY | quote }}
- name: ADCS_INGESTION_RETRY_MAX_ATTEMPTS
  value: {{ .Values.global.env.ADCS_INGESTION_RETRY_MAX_ATTEMPTS | quote }}
- name: ADCS_INGESTION_RETRY_BACKOFF_BASE_SECONDS
  value: {{ .Values.global.env.ADCS_INGESTION_RETRY_BACKOFF_BASE_SECONDS | quote }}
- name: ADCS_INGESTION_RETRY_BACKOFF_MAX_SECONDS
  value: {{ .Values.global.env.ADCS_INGESTION_RETRY_BACKOFF_MAX_SECONDS | quote }}
- name: ADCS_TRANSLATION_LLM_CONFIG_PATH
  value: {{ .Values.global.configPaths.ADCS_TRANSLATION_LLM_CONFIG_PATH | quote }}
- name: ADCS_INGESTION_LLM_POLICY_CONFIG_PATH
  value: {{ .Values.global.configPaths.ADCS_INGESTION_LLM_POLICY_CONFIG_PATH | quote }}
- name: ADCS_INGESTION_PROMPT_REGISTRY_CONFIG_PATH
  value: {{ .Values.global.configPaths.ADCS_INGESTION_PROMPT_REGISTRY_CONFIG_PATH | quote }}
- name: ADCS_LAYOUT_DETECTION_CONFIDENCE_THRESHOLD
  value: {{ .Values.global.env.ADCS_LAYOUT_DETECTION_CONFIDENCE_THRESHOLD | quote }}
- name: ADCS_LAYOUT_DETECTION_ALLOW_MANUAL_OVERRIDE
  value: {{ .Values.global.env.ADCS_LAYOUT_DETECTION_ALLOW_MANUAL_OVERRIDE | quote }}
- name: ADCS_QUALITY_GATES_PHASE
  value: {{ .Values.global.env.ADCS_QUALITY_GATES_PHASE | quote }}
- name: ADCS_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "adcs.fullname" . }}-secrets
      key: ADCS_API_KEY
- name: ADCS_HASH_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "adcs.fullname" . }}-secrets
      key: ADCS_HASH_SECRET
- name: ADCS_EMBEDDING_BACKEND
  value: {{ .Values.global.env.ADCS_EMBEDDING_BACKEND | quote }}
- name: ADCS_EMBEDDING_API_URL
  value: {{ .Values.global.env.ADCS_EMBEDDING_API_URL | quote }}
{{- with .Values.global.env.ADCS_EMBEDDING_MODEL }}
- name: ADCS_EMBEDDING_MODEL
  value: {{ . | quote }}
{{- end }}
- name: ADCS_EMBEDDING_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "adcs.fullname" . }}-secrets
      key: ADCS_EMBEDDING_API_KEY
{{- range $name, $value := .Values.global.extraEnv }}
- name: {{ $name }}
  value: {{ $value | quote }}
{{- end }}
{{- end -}}

{{/*
Source directory skeleton. SourceRegistryService validates at start-up that every source
root and repository path listed in config/source-repositories.yaml exists. The corpus is
not baked into the images, so an init container creates the directory skeleton in an
emptyDir that each workload mounts at /app/source-repo-apiref and /app/source-repo-docs.
Replace the emptyDir with a real corpus volume when a pod needs the raw markdown.
*/}}
{{- define "adcs.sourceDirs.initContainer" -}}
- name: create-source-dirs
  image: {{ .image | quote }}
  imagePullPolicy: {{ .pullPolicy }}
  command:
    - python
    - -c
    - |
      import os
      import yaml
      with open("/app/config/source-repositories.yaml", encoding="utf-8") as fh:
          registry = yaml.safe_load(fh)
      paths = [root["path"] for root in registry["source_roots"]]
      paths += [repo["git"]["submodule_path"] for repo in registry["repositories"]]
      for path in paths:
          os.makedirs(os.path.join("/source", path), exist_ok=True)
  volumeMounts:
    - name: source-dirs
      mountPath: /source
{{- end -}}

{{- define "adcs.sourceDirs.volumeMounts" -}}
- name: source-dirs
  mountPath: /app/source-repo-apiref
  subPath: source-repo-apiref
- name: source-dirs
  mountPath: /app/source-repo-docs
  subPath: source-repo-docs
{{- end -}}

{{- define "adcs.sourceDirs.volume" -}}
- name: source-dirs
  emptyDir: {}
{{- end -}}
