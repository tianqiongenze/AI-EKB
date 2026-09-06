#!/usr/bin/env bash
set -euo pipefail

install_with_brew() {
  brew list "$1" >/dev/null 2>&1 || brew install "$1"
}

if command -v brew >/dev/null 2>&1; then
  echo "[bootstrap] using Homebrew"
  install_with_brew go
  install_with_brew maven
  install_with_brew jdtls
  install_with_brew gopls
  install_with_brew yaml-language-server
elif command -v apt-get >/dev/null 2>&1; then
  echo "[bootstrap] using apt-get"
  sudo apt-get update
  sudo apt-get install -y curl git python3 python3-pip golang-go maven default-jdk
  if ! command -v gopls >/dev/null 2>&1; then
    GO111MODULE=on go install golang.org/x/tools/gopls@latest
    export PATH="$PATH:$(go env GOPATH)/bin"
  fi
  if ! command -v yaml-language-server >/dev/null 2>&1; then
    sudo npm install -g yaml-language-server
  fi
else
  echo "[bootstrap] unsupported package manager: require brew or apt-get" >&2
  exit 1
fi

PYTHON_BIN=""
if command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="python3.11"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "[bootstrap] python3 not found" >&2
  exit 1
fi

echo "[bootstrap] Installing python dependencies via ${PYTHON_BIN}..."
"${PYTHON_BIN}" -m pip install --upgrade pip
"${PYTHON_BIN}" -m pip install grpcio-tools pyyaml

echo "[bootstrap] Verifying toolchain..."
"${PYTHON_BIN}" scripts/check_dev_toolchain.py

echo "[bootstrap] Completed successfully."
