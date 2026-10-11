{{- define "pifanctl.operatorName" -}}
{{ printf "%s-operator" .Release.Name | trunc 57 | trimSuffix "-" }}
{{- end -}}
{{- define "pifanctl.operatorImage" -}}
{{ printf "%s:%s" .Values.image.repository (default (printf "v%s" .Chart.AppVersion) .Values.image.tag) }}
{{- end -}}
{{- define "pifanctl.operatorLabels" -}}
app.kubernetes.io/name: pifanctl-operator
app.kubernetes.io/instance: {{ .Release.Name }}
pifanctl.jyje.online/operator: {{ .Values.operatorId | quote }}
{{- end -}}
{{- define "pifanctl.workerNamespace" -}}
{{ default .Release.Namespace .Values.workerNamespace }}
{{- end -}}
{{- define "pifanctl.separateWorkers" -}}
{{- if ne (include "pifanctl.workerNamespace" .) .Release.Namespace -}}true{{- end -}}
{{- end -}}
