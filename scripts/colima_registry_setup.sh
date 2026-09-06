#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

source "$ROOT_DIR/scripts/colima_runtime.sh"

ensure_cmd jq
ensure_colima_runtime
if ! command -v python3 >/dev/null 2>&1; then
  echo "[colima-registry] python3 command not found"
  exit 1
fi

COLIMA_CFG="$HOME/.colima/default/colima.yaml"

if [[ ! -f "$COLIMA_CFG" ]]; then
  echo "[colima-registry] missing config: $COLIMA_CFG"
  exit 1
fi

if ! grep -q "registry-mirrors:" "$COLIMA_CFG"; then
  cat >> "$COLIMA_CFG" <<'EOF'
docker:
  registry-mirrors:
    - https://docker.m.daocloud.io
EOF
fi

if ! grep -q "https://docker.m.daocloud.io" "$COLIMA_CFG"; then
  python3 - <<'PY'
from pathlib import Path
cfg = Path.home() / ".colima" / "default" / "colima.yaml"
text = cfg.read_text(encoding="utf-8")
if "registry-mirrors:" in text:
    text = text.replace("registry-mirrors:\n", "registry-mirrors:\n    - https://docker.m.daocloud.io\n", 1)
cfg.write_text(text, encoding="utf-8")
PY
fi

DOCKER_CFG="$HOME/.docker/config.json"
if [[ ! -f "$DOCKER_CFG" ]]; then
  mkdir -p "$HOME/.docker"
  cat > "$DOCKER_CFG" <<'EOF'
{
  "auths": {},
  "currentContext": "colima",
  "cliPluginsExtraDirs": [
    "/opt/homebrew/lib/docker/cli-plugins"
  ]
}
EOF
else
  tmp="$(mktemp)"
  jq '. + {"currentContext":"colima","cliPluginsExtraDirs":((.cliPluginsExtraDirs // []) + ["/opt/homebrew/lib/docker/cli-plugins"] | unique)}' "$DOCKER_CFG" > "$tmp"
  mv "$tmp" "$DOCKER_CFG"
fi

colima stop || true
colima start
docker context use colima >/dev/null
docker buildx version >/dev/null

echo "[colima-registry] done"
