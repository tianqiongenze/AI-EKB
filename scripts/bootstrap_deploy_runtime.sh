#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-local}"

install_with_brew() {
  brew list "$1" >/dev/null 2>&1 || brew install "$1"
}

install_with_apt() {
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg lsb-release software-properties-common
}

if command -v brew >/dev/null 2>&1; then
  echo "[runtime-bootstrap] using Homebrew"
  install_with_brew jq
  install_with_brew docker
  install_with_brew colima
  install_with_brew docker-buildx
  install_with_brew docker-compose
  if [[ "$MODE" == "k8s" ]]; then
    install_with_brew kubectl
    install_with_brew helm
    install_with_brew kind
  fi
elif command -v apt-get >/dev/null 2>&1; then
  echo "[runtime-bootstrap] using apt-get"
  install_with_apt
  if ! command -v docker >/dev/null 2>&1; then
    sudo apt-get install -y docker.io docker-compose-plugin
    sudo systemctl enable --now docker || true
  fi
  if [[ "$MODE" == "k8s" ]]; then
    if ! command -v kubectl >/dev/null 2>&1; then
      KUBECTL_VERSION="$(curl -L -s https://dl.k8s.io/release/stable.txt)"
      curl -L -o /tmp/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
      sudo install -m 0755 /tmp/kubectl /usr/local/bin/kubectl
    fi
    if ! command -v helm >/dev/null 2>&1; then
      curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
    fi
  fi
else
  echo "[runtime-bootstrap] unsupported package manager: require brew or apt-get" >&2
  exit 1
fi

echo "[runtime-bootstrap] completed"
