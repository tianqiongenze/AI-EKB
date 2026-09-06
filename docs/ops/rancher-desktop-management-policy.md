# Rancher Desktop Management Policy

## Scope

This policy constrains local operations to Rancher Desktop-managed Kubernetes workflows.

## Mandatory Rules

1. Primary UI/management entrypoint is Rancher Desktop (`/Applications/Rancher Desktop.app`).
2. All namespace/service/deployment operations must be executed against the Rancher-managed kube context.
3. One-click lifecycle operations must be triggered through:
   - `scripts/one_click_rancher_multiactive.sh`
4. Release dry-run and compliance checks must be run through:
   - `scripts/run_production_param_dryrun.py`
5. Multi-env application-plane rollout must be run through:
   - `scripts/run_multi_env_multiactive_light.py`

## Recommended Operating Sequence

1. Start Rancher Desktop and verify Kubernetes is enabled.
2. Verify current context points to Rancher-managed cluster.
3. Run one-click script for shutdown + redeploy + failover pressure.
4. Run production parameterized dry-run and confirm `status=ok`.

## Evidence Files

- `perf/reports/rancher-oneclick-ops-summary.json`
- `perf/reports/multi-env-multiactive-summary.json`
- `perf/reports/multiregion-failover-load-summary.json`
- `perf/reports/production-param-dryrun-summary.json`
