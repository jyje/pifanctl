# Isolated Kubernetes runtime lab

This image layer replaces only RPi.GPIO and thermal sensor I/O with explicit
simulations. It runs the candidate application's unmodified planner, Kubernetes
client, operator, worker, host locks, watchdogs, reports and finalizers.

Never publish or deploy this image to a hardware cluster. The adapter exits if
its explicit lab marker is missing. GPIO calls emit inspectable JSON to worker
logs. Temperatures default to 55 C and can be changed through the lab-only
`lab-temperature-celsius` key in the operator-created worker plan ConfigMap.
Missing or malformed input produces a missing local sensor.

The verification harness must require context `kind-pifanctl-release`. These
results establish Kubernetes/runtime software behavior, not actual PWM, fan RPM,
electrical defaults, cooling capacity or hardware failure recovery. The lab does
not change the production application's driver or CRD support contracts.

## Node preparation and reproduction

The kind node used here has `/var/lock -> /run/lock` but initially lacks
`/run/lock`. Prepare this OS directory before the trial. The operator's hostPath
remains `/var/lock/pifanctl` so the existing host lock identity is preserved.
Do not clear resource finalizers to work around a failed worker.

```sh
docker exec pifanctl-release-control-plane mkdir -p /run/lock
docker build -f docker/all.dockerfile -t pifanctl-runtime-candidate:alpha6 .
docker build -f tests/runtime_lab/Dockerfile \
  --build-arg BASE_IMAGE=pifanctl-runtime-candidate:alpha6 \
  -t pifanctl-runtime-lab:alpha6 .
kind load docker-image pifanctl-runtime-lab:alpha6 --name pifanctl-release
```

Install the operator using a separate kubeconfig for every command. Network
policy is disabled only in this disposable lab because kind has no policy CNI:

```sh
helm upgrade --install pifanctl-release charts/pifanctl-operator \
  --kubeconfig /private/tmp/pifanctl-release.kubeconfig \
  --namespace pifanctl-release --create-namespace \
  --set image.repository=pifanctl-runtime-lab --set image.tag=alpha6 \
  --set image.pullPolicy=Never --set agent.mode=reuse \
  --set networkPolicy.enabled=false
kubectl --kubeconfig /private/tmp/pifanctl-release.kubeconfig \
  --namespace pifanctl-release rollout status \
  deployment/pifanctl-release-operator --timeout=120s
```

Then run:

```sh
python scripts/verify_runtime_lifecycle.py \
  --kubeconfig /private/tmp/pifanctl-release.kubeconfig \
  --report /private/tmp/pifanctl-runtime-lifecycle-alpha6.json \
  --logs /private/tmp/pifanctl-runtime-lifecycle-alpha6.txt
```

The first alpha.5 trial failed before Python started because its hostPath
traversed the dangling node symlink. Creating the target directory restored
the node prerequisite. The alpha.6 candidate also mounts the lock at the direct
container path `/run/lock/pifanctl`. These are separate changes; the trial does
not establish that changing the container path alone fixes the host failure.
