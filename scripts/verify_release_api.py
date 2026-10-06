#!/usr/bin/env python3
"""Validate release fixtures in an isolated kind cluster without GPIO access."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--exercise-lifecycle", action="store_true")
    args = parser.parse_args()
    prefix = ["kubectl", "--kubeconfig", str(args.kubeconfig)]

    def command(*parts, body=None):
        return subprocess.run(prefix + list(parts), input=json.dumps(body) if body else None,
                              text=True, capture_output=True, timeout=30)

    def get(*parts):
        result = command("get", *parts, "-o", "json")
        if result.returncode:
            raise RuntimeError(result.stderr)
        return json.loads(result.stdout)

    context = command("config", "current-context").stdout.strip()
    if context != "kind-pifanctl-release":
        raise SystemExit("Refusing release fixtures outside kind-pifanctl-release")

    checks = []

    def check(name, passed, details):
        checks.append({"name": name, "passed": bool(passed), "details": details})

    for kind in ("fans", "coolingzones"):
        crd = get("crd", kind + ".pifanctl.jyje.online")
        established = any(c["type"] == "Established" and c["status"] == "True"
                          for c in crd["status"]["conditions"])
        check(kind + "_established", established, "apiextensions.k8s.io/v1 status")

    fan = get("fan", "rack-fan-01")
    zone = get("coolingzone", "rack-a")
    check("fan_curve_defaulting", fan["spec"]["control"]["curve"]["temperatureHysteresis"] == 5,
          "API defaulted temperatureHysteresis to 5")
    for name, obj, reason in (("fan_missing_node", fan, "MissingWorkerNode"),
                              ("zone_empty_selection", zone, "EmptySelection")):
        conditions = obj["status"]["conditions"]
        check(name, any(c["type"] == "Ready" and c["status"] == "False" and
                       c["reason"] == reason for c in conditions), reason)

    deployment = get("deployment", "pifanctl-release-operator", "-n", "pifanctl-release")
    check("operator_available", deployment["status"].get("availableReplicas") == 1,
          "One available operator replica")
    deployments = get("deployment", "-n", "pifanctl-release")["items"]
    check("no_hardware_worker", len(deployments) == 1 and
          deployments[0]["metadata"]["name"] == "pifanctl-release-operator",
          "Missing-node fixtures must not create a worker")

    def rejected(name, mutate, error_field):
        obj = deepcopy(fan)
        mutate(obj)
        result = command("replace", "--dry-run=server", "-f", "-", body=obj)
        valid_error = result.returncode != 0 and "Invalid" in result.stderr and error_field in result.stderr
        check(name, valid_error, result.stderr.strip())

    rejected("curve_order_rejected", lambda x: x["spec"]["control"]["curve"].update(
        temperatureHigh=40), "temperatureLow")
    rejected("zero_frequency_rejected", lambda x: x["spec"]["hardware"]["rpigpio"].update(
        frequencyHz=0), "frequencyHz")
    rejected("immutable_node_rejected", lambda x: x["spec"].update(nodeName="different-node"), "nodeName")
    rejected("immutable_hardware_rejected", lambda x: x["spec"]["hardware"]["rpigpio"].update(
        pin=19), "hardware")

    if args.exercise_lifecycle:
        suffix = uuid.uuid4().hex[:8]
        fan_name, zone_name = "delete-fan-" + suffix, "delete-zone-" + suffix
        created = []
        try:
            for kind, original, obj_name in (("Fan", fan, fan_name), ("CoolingZone", zone, zone_name)):
                obj = {"apiVersion": original["apiVersion"], "kind": kind,
                       "metadata": {"name": obj_name}, "spec": deepcopy(original["spec"])}
                if kind == "CoolingZone":
                    obj["spec"]["fanRefs"] = [fan_name]
                result = command("create", "-f", "-", body=obj)
                if result.returncode:
                    raise RuntimeError(result.stderr)
                created.append((kind, obj_name))
                deadline = time.monotonic() + 30
                finalized = False
                while time.monotonic() < deadline:
                    current = get(kind, obj_name)
                    finalized = "pifanctl.jyje.online/release" in current["metadata"].get("finalizers", [])
                    if finalized:
                        break
                    time.sleep(1)
                check(kind.lower() + "_finalizer_added", finalized,
                      "Operator attached the release finalizer to a missing-node probe")
        finally:
            for kind, obj_name in reversed(created):
                result = command("delete", kind, obj_name, "--wait=true", "--timeout=20s")
                check(kind.lower() + "_finalizer_cleanup", result.returncode == 0,
                      result.stdout.strip() if result.returncode == 0 else result.stderr.strip())

    nodes = get("nodes")["items"]
    report = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "context": context,
        "kubernetes_versions": sorted({n["status"]["nodeInfo"]["kubeletVersion"] for n in nodes}),
        "operator_image": deployment["spec"]["template"]["spec"]["containers"][0]["image"],
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
        "scope": "Real API admission/defaulting and missing-node reconciliation/lifecycle; no active worker, GPIO, Argo ordering, migration, or electrical acceptance",
    }
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
