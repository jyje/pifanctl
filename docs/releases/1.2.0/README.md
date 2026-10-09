# v1.2.0 release verification

Application and supported operator chart 1.2.0 were published on 2026-10-09 from
`083f50ed5865384f8238fe62d480344ff3bb5d66` (PR #74). The chart default appVersion
is 1.2.0. Published version tags retain this release source revision.

## Published artifacts

| Artifact | Reference | Digest |
| --- | --- | --- |
| ARM64 Python 3.14 app | `ghcr.io/jyje/pifanctl:v1.2.0` | `sha256:c26b238e03d0d7c9bd2a4ecf3c7b57a92568f260b4ac4b7dba0798745f35a762` |
| ARM64 Python 3.12 compatibility app | `ghcr.io/jyje/pifanctl:v1.2.0-py312` | `sha256:afcf087cad98fed4a72cffca120733a47fb7093d953a7ddf3a6d724316fc12a5` |
| Operator chart | `oci://ghcr.io/jyje/charts/pifanctl-operator`, version `1.2.0` | `sha256:bb2772f80f6344e5063d93919e5d98547f20133f435e7ff6ddfbf4e384389cb8` |

Image manifests were inspected with `docker buildx imagetools inspect`; the OCI
chart was downloaded and inspected with `helm show chart`. Default and
compatibility images passed the release workflow's container smoke checks.

- [App release workflow](https://github.com/jyje/pifanctl/actions/runs/37866477844): passed.
- [Chart release workflow](https://github.com/jyje/pifanctl/actions/runs/37866477722): passed.
- [Main CI](https://github.com/jyje/pifanctl/actions/runs/37866477570): passed, including Python 3.10-3.14 and fresh badge-revision coverage upload.
- [App release notes](https://github.com/jyje/pifanctl/releases/tag/v1.2.0).
- [Chart release notes](https://github.com/jyje/pifanctl/releases/tag/operator-chart-v1.2.0).

## Coverage provenance

The generated badge commit is `249128a64f6f819f70d316a355c44de84da7f117`.
The publisher ran the Python 3.14 suite again on that commit and uploaded newly
measured XML with that SHA. Codecov project and patch statuses both passed for
the badge revision. The earlier source XML was not reassigned to a different SHA.
Complete PR comments remain enabled; project coverage is 94.46%, while PR #74's
patch coverage is 100%. These are different metrics.

## Upgrade and operational boundary

Review and explicitly apply the additive CRD schema before enabling
`Fan.spec.feedback.pwm`. Existing values remain compatible, and feedback is
opt-in. Follow the [probe guide](../../v1/pwm-probe.md) for Pi-safe wiring,
measurement availability and rollback sequencing.

This release verification covers published artifacts and automated checks.
Physical PWM probe accuracy and high-frequency event capture remain unverified.
This release closeout does not activate a probe or update cluster GitOps.
