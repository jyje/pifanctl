import json
import pathlib
import shutil
import subprocess

import pytest
import yaml

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
    # The v0 chart retains its independently pinned compatibility image.
    assert chart["appVersion"] == "1.0.0-alpha.2"


def test_image_tag_defaults_to_the_app_version_never_latest():
    agent = by_name(render(), "DaemonSet")["t-pifanctl-agent"]
    image = agent["spec"]["template"]["spec"]["containers"][0]["image"]
    chart = yaml.safe_load((CHART / "Chart.yaml").read_text())
    assert image == f"ghcr.io/jyje/pifanctl:v{chart['appVersion']}"


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


def test_the_curve_has_the_official_five_degree_hysteresis_by_default():
    controller = by_name(render(), "DaemonSet")["t-pifanctl-controller-default"]
    assert env(controller)["TEMP_HYSTERESIS"] == "5"


def test_hysteresis_can_be_changed_per_group_and_turned_off():
    controller = by_name(render("--set", "controllerDefaults.curve.hysteresis=0"), "DaemonSet")["t-pifanctl-controller-default"]
    assert env(controller)["TEMP_HYSTERESIS"] == "0"
    out = subprocess.run(["helm", "template", "t", str(CHART), "--set", "controllerDefaults.curve.hysteresis=-1"],
                         capture_output=True, text=True)
    assert out.returncode != 0


def test_prometheus_url_switches_the_source():
    objects = render("--set", "prometheus.url=http://prom:9090")
    values = env(by_name(objects, "DaemonSet")["t-pifanctl-controller-default"])
    assert values["SOURCE"] == "prometheus"
    assert values["PROMETHEUS_URL"] == "http://prom:9090"
    assert values["PROMETHEUS_QUERY"] == "max by (node) (pifanctl_temperature_celsius)"


def test_a_groups_node_selector_replaces_instead_of_merging():
    # Helm merges maps, so a selector written for a group must not pick up
    # the chart's fan label: that combination matches no node at all.
    sets = by_name(render("--set", "controllers.default.nodeSelector.kubernetes\\.io/hostname=node-a"), "DaemonSet")
    selector = sets["t-pifanctl-controller-default"]["spec"]["template"]["spec"]["nodeSelector"]
    assert selector == {"kubernetes.io/hostname": "node-a"}


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
    out = subprocess.run(["helm", "template", "t", str(CHART), "--set", "controllers.default.nodeSelector.a=b",
                          "--set", "controllers.default.source=prometheus"],
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


def test_controller_runs_as_root_because_the_image_does_not():
    # The image defaults to a non-root user, but RPi.GPIO maps /dev/mem. Without
    # this the controller crash-loops with "No access to /dev/mem" on real
    # hardware, which no unit test can reproduce.
    controller = by_name(render(), "DaemonSet")["t-pifanctl-controller-default"]
    pod = controller["spec"]["template"]["spec"]
    assert pod["securityContext"] == {"runAsUser": 0, "runAsNonRoot": False}
    assert pod["containers"][0]["securityContext"]["privileged"] is True
    agent = by_name(render(), "DaemonSet")["t-pifanctl-agent"]["spec"]["template"]["spec"]
    assert agent["securityContext"]["runAsNonRoot"] is True


def test_the_raw_manifest_and_the_install_command_follow_the_release():
    chart = yaml.safe_load((CHART / "Chart.yaml").read_text())
    manifest = (CHART.parent.parent / "k8s" / "manifests" / "deployments.yaml").read_text()
    assert f"ghcr.io/jyje/pifanctl:v{chart['appVersion']}" in manifest
    for readme in ("README.md", "README-ko.md"):
        text = (CHART.parent.parent / readme).read_text()
        assert f"--version {chart['version']}" in text, f"{readme} installs a different chart version"
