param(
  [ValidateSet("local", "k8s")]
  [string]$Mode = "local"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "[one-click-ps] mode=$Mode"

if ($Mode -eq "local") {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker is required"
  }
  docker compose -f "$Root/infra/docker-compose.phase3.yml" up -d --build
} else {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "docker is required" }
  if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) { throw "kubectl is required" }
  if (-not (Get-Command helm -ErrorAction SilentlyContinue)) { throw "helm is required" }
  if (-not $env:AWS_ACCESS_KEY_ID -or -not $env:AWS_SECRET_ACCESS_KEY) {
    throw "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set"
  }

  $repo = if ($env:FLINK_IMAGE_REPO) { $env:FLINK_IMAGE_REPO } else { "ghcr.io/local/yadea-ekb" }
  $tag = if ($env:FLINK_IMAGE_TAG) { $env:FLINK_IMAGE_TAG } else { "local" }
  $image = "$repo/yadea-ekb-flink-session:$tag"

  docker build -t $image "$Root/services/flink-session-image"
  if (Get-Command kind -ErrorAction SilentlyContinue) {
    kind load docker-image $image
  }

  kubectl apply -k "$Root/infra/k8s/deps"
  python "$Root/scripts/verify_k8s_stack.py"
  kubectl apply -k "$Root/infra/kustomize/base"

  helm upgrade --install ekb-control-plane "$Root/infra/helm/ekb-control-plane" --namespace ekb-control-plane --create-namespace
  helm upgrade --install ekb-flink-jobs "$Root/infra/helm/ekb-flink-jobs" --namespace ekb-control-plane --set sessionCluster.image="$image" --set credentials.awsAccessKeyId="$env:AWS_ACCESS_KEY_ID" --set credentials.awsSecretAccessKey="$env:AWS_SECRET_ACCESS_KEY"

  python "$Root/scripts/verify_k8s_stack.py"
}

python "$Root/scripts/check_dev_toolchain.py"
python "$Root/scripts/check_contract_consistency.py"
python "$Root/scripts/check_flink_runtime_preflight_contract.py"
python "$Root/scripts/check_replay_e2e_slo.py"

Write-Host "[one-click-ps] done"
