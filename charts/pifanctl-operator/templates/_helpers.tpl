{{- define "pifanctl.operatorName" -}}
{{ printf "%s-operator" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end -}}
{{- define "pifanctl.operatorImage" -}}
{{ printf "%s:%s" .Values.image.repository (default (printf "v%s" .Chart.AppVersion) .Values.image.tag) }}
{{- end -}}
{{- define "pifanctl.operatorLabels" -}}
app.kubernetes.io/name: pifanctl-operator
app.kubernetes.io/instance: {{ .Release.Name }}
pifanctl.jyje.online/operator: {{ .Values.operatorId | quote }}
{{- end -}}
