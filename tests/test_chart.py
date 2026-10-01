import json
import pathlib
import shutil
import subprocess

import pytest
import yaml

import pifanctl

CHART = pathlib.Path(__file__).resolve().parent.parent / "charts" / "pifanctl"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def render(*args: str, values: str | None = None) -> list[dict]:
    command = ["helm", "template", "t", str(CHART), "-n", "pifan", *args]
    if values:
        command += ["-f", str(CHART / "ci" / values)]
    out = subprocess.run(command, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return [d for d in yaml.safe_load_all(out.stdout) if d]


def by_name(objects, kind):
    return {o["metadata"]["name"]: o for o in objects if o["kind"] == kind}


def env(daemonset) -> dict:
    container = daemonset["spec"]["template"]["spec"]["containers"][0]
    return {e["name"]: e.get("value") for e in container["env"]}


def test_chart_app_version_matches_the_application():
    chart = yaml.safe_load((CHART / "Chart.yaml").read_text())
    assert chart["appVersion"] == pifanctl.__version__


def test_image_tag_defaults_to_the_app_version_never_latest():
    agent = by_name(render(), "DaemonSet")["t-pifanctl-agent"]
    image = agent["spec"]["template"]["spec"]["containers"][0]["image"]
    assert image == f"ghcr.io/jyje/pifanctl:v{pifanctl.__version__}"


def test_agent_runs_on_every_node_unprivileged():
    agent = by_name(render(), "DaemonSet")["t-pifanctl-agent"]
    spec = agent["spec"]["template"]["spec"]
    assert "nodeSelector" not in spec
    assert {"operator": "Exists"} in spec["tolerations"]
    context = spec["containers"][0]["securityContext"]
    assert context["readOnlyRootFilesystem"] is True
    assert context["allowPrivilegeEscalation"] is False
    assert spec["securityContext"]["runAsNonRoot"] is True


def test_controller_is_pinned_to_fan_nodes_by_label():
    controller = by_name(render(), "DaemonSet")["t-pifanctl-controller-default"]
    assert controller["spec"]["template"]["spec"]["nodeSelector"] == {"pifanctl.jyje.online/fan": "true"}


def test_controller_defaults_are_fail_safe():
    values = env(by_name(render(), "DaemonSet")["t-pifanctl-controller-default"])
    assert values["FAILSAFE_DUTY"] == "100" and values["EXIT_DUTY"] == "100"
    assert values["SOURCE"] == "local"
    assert "PROMETHEUS_URL" not in values


def test_prometheus_url_switches_the_source():
    objects = render("--set", "prometheus.url=http://prom:9090")
    values = env(by_name(objects, "DaemonSet")["t-pifanctl-controller-default"])
    assert values["SOURCE"] == "prometheus"
    assert values["PROMETHEUS_URL"] == "http://prom:9090"
    assert values["PROMETHEUS_QUERY"] == "max by (node) (pifanctl_temperature_celsius)"


def test_groups_override_defaults_per_hardware():
    sets = by_name(render(values="mixed-hardware-values.yaml"), "DaemonSet")
    assert "t-pifanctl-controller-default" not in sets
    pi4, pi5 = env(sets["t-pifanctl-controller-pi4"]), env(sets["t-pifanctl-controller-pi5"])
    assert (pi4["DRIVER"], pi4["TEMP_LOW"]) == ("rpigpio", "55")
    assert (pi5["DRIVER"], pi5["TEMP_LOW"]) == ("sysfs", "50")
    assert pi5["PROMETHEUS_QUERY"] == 'max by (node) (pifanctl_temperature_celsius{node=~"raspi-5.*"})'
    assert pi4["PROMETHEUS_QUERY"] == "max by (node) (pifanctl_temperature_celsius)"


def test_a_group_without_a_node_selector_is_rejected():
    out = subprocess.run(["helm", "template", "t", str(CHART), "--set", "controllers.oops.enabled=true"],
                         capture_output=True, text=True)
    assert out.returncode != 0 and "needs a nodeSelector" in out.stderr


def test_prometheus_source_without_a_url_is_rejected():
    out = subprocess.run(["helm", "template", "t", str(CHART), "--set", "controllers.default.source=prometheus"],
                         capture_output=True, text=True)
    assert out.returncode != 0 and "prometheus.url is required" in out.stderr


def test_invalid_values_are_rejected_by_the_schema():
    out = subprocess.run(["helm", "template", "t", str(CHART), "--set", "controllerDefaults.driver=banana"],
                         capture_output=True, text=True)
    assert out.returncode != 0


def test_monitoring_objects_are_opt_in_and_complete():
    assert not {o["kind"] for o in render()} & {"ServiceMonitor", "PrometheusRule", "GrafanaDashboard"}
    kinds = {o["kind"] for o in render(values="prometheus-values.yaml")}
    assert {"ServiceMonitor", "PrometheusRule", "GrafanaDashboard"} <= kinds


def test_alert_rules_cover_the_failure_modes():
    rule = by_name(render(values="prometheus-values.yaml"), "PrometheusRule")["t-pifanctl"]
    alerts = {r["alert"] for g in rule["spec"]["groups"] for r in g["rules"] if "alert" in r}
    assert {"PifanctlNodeHot", "PifanctlNodeCritical", "PifanctlAgentDown",
            "PifanctlControllerFailsafe", "PifanctlControllerFallback", "PifanctlControllerMissing"} <= alerts


def test_dashboard_is_embedded_unchanged():
    expected = json.loads((CHART / "dashboards" / "pifanctl.json").read_text())
    objects = render("--set", "monitoring.grafanaDashboard.enabled=true")
    config_map = by_name(objects, "ConfigMap")["t-pifanctl-dashboard"]
    assert json.loads(config_map["data"]["pifanctl.json"]) == expected


def test_dashboard_namespace_can_differ_from_the_release():
    dashboard = [o for o in render(values="prometheus-values.yaml") if o["kind"] == "GrafanaDashboard"][0]
    assert dashboard["metadata"]["namespace"] == "observability"
    default = [o for o in render("--set", "monitoring.grafanaDashboard.enabled=true") if o["metadata"]["name"].endswith("-dashboard")][0]
    assert default["metadata"]["namespace"] == "pifan"
