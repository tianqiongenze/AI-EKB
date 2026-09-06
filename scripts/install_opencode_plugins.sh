#!/usr/bin/env bash
set -euo pipefail

# Global Opencode plugins installation
# Supported package managers: npm (preferred), yarn, fall back to pip3

# Use lowercase plugin identifiers for compatibility
PLUGINS=(oh-my-openagent superpowers @fission-ai/openspec @tarquinen/opencode-dcp @cortexkit/opencode-magic-context)

install_with_npm() {
  npm install -g "$1"
}

if command -v npm >/dev/null 2>&1; then
  echo "Installing Opencode plugins via npm..."
  for p in "${PLUGINS[@]}"; do
    echo "Installing npm plugin: $p"
    if install_with_npm "$p"; then
      echo "Installed $p"
    else
      echo "Failed to install $p via npm; attempting pip fallback if available..."
      if command -v python3 >/dev/null 2>&1; then
        if python3 -m pip install --user "$p"; then
          echo "Installed $p via pip"
        else
          echo "No viable installation path for $p; continuing..." >&2
        fi
      else
        echo "Python3 not available; continuing..." >&2
      fi
    fi
  done
elif command -v yarn >/dev/null 2>&1; then
  echo "Installing Opencode plugins via yarn..."
  for p in "${PLUGINS[@]}"; do
    echo "Installing yarn global plugin: $p"
    if yarn global add "$p"; then
      echo "Installed $p"
    else
      echo "Failed to install $p via yarn" >&2
      exit 1
    fi
  done
else
  echo "No npm or yarn found. Trying Python-based installation as fallback..."
  if command -v pip3 >/dev/null 2>&1; then
    for p in "${PLUGINS[@]}"; do
      echo "Installing Python package: $p"
      if python3 -m pip install --user "$p"; then
        echo "Installed $p via pip"
      else
        echo "Failed to install $p via pip" >&2
        exit 1
      fi
    done
  else
    echo "No package manager available (npm/yarn/pip). Aborting plugin installation." >&2
    exit 2
  fi
fi

echo "Plugin installation complete. Verifying binaries in PATH..."
for p in "${PLUGINS[@]}"; do
  if command -v "$p" >/dev/null 2>&1; then
    echo "Verified: $p"
  else
    echo "Warning: $p not found in PATH. You may need to configure PATH or install a wrapper." >&2
  fi
done

# Persist a default OpenCode global plugin configuration so new shells pick up plugins
CONFIG_DIR="${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}"
CONFIG_FILE="$CONFIG_DIR/opencode.json"
mkdir -p "$CONFIG_DIR"
cat > "$CONFIG_FILE" << 'JSON'
{
  "plugin": [
    "oh-my-openagent",
    "@fission-ai/openspec",
    "@tarquinen/opencode-dcp",
    "@cortexkit/opencode-magic-context"
  ]
}
JSON
echo "Wrote default OpenCode plugin config to $CONFIG_FILE"
