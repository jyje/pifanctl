{{- define "pifanctl.topologyItems" -}}
{{- $items := list -}}
{{- range $name, $spec := .Values.fans -}}
{{- $items = append $items (dict "apiVersion" "pifanctl.jyje.online/v1" "kind" "Fan" "metadata" (dict "name" $name) "spec" $spec) -}}
{{- end -}}
{{- range $name, $spec := .Values.coolingZones -}}
{{- range $fan := $spec.fanRefs -}}
{{- if not (hasKey $.Values.fans $fan) -}}
{{- fail (printf "coolingZones.%s refers to undefined fan %s" $name $fan) -}}
{{- end -}}
{{- end -}}
{{- $items = append $items (dict "apiVersion" "pifanctl.jyje.online/v1" "kind" "CoolingZone" "metadata" (dict "name" $name) "spec" $spec) -}}
{{- end -}}
{{- toYaml (dict "items" $items) -}}
{{- end -}}
