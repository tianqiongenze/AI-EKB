#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-local}"

if ! command -v apt-get >/dev/null 2>&1; then
  echo "[runtime-bootstrap-linux] apt-get required" >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release software-properties-common docker.io docker-compose-plugin
sudo systemctl enable --now docker || true

if [[ "$MODE" == "k8s" ]]; then
  if ! command -v kubectl >/dev/null 2>&1; then
    KUBECTL_VERSION="$(curl -L -s https://dl.k8s.io/release/stable.txt)"
    curl -L -o /tmp/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
    sudo install -m 0755 /tmp/kubectl /usr/local/bin/kubectl
  fi
  if ! command -v helm >/dev/null 2>&1; then
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
  fi
  if ! command -v kind >/dev/null 2>&1; then
    KIND_VERSION="v0.23.0"
    curl -Lo ./kind https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-amd64
    chmod +x ./kind
    sudo mv ./kind /usr/local/bin/kind
  fi
fi

echo "[runtime-bootstrap-linux] completed"
