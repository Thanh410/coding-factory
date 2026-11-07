#!/usr/bin/env bash
# bootstrap.sh - one-shot setup for a 24/7 worker on a fresh Linux host.
#
# Installs Python deps, the Codex CLI, the systemd unit, and starts the service.
# Run as a user with sudo. Edit the Environment= lines first (API keys, repo).
set -euo pipefail

REPO_DIR="$(pwd)"
UNIT_NAME="coding-factory"

echo ">> installing python package"
python3 -m pip install --user -e "$REPO_DIR"

if command -v codex >/dev/null 2>&1; then
  echo ">> codex already installed"
else
  echo ">> installing codex CLI"
  npm install -g @openai/codex
fi

echo ">> installing systemd unit"
sed "s#__REPO_DIR__#${REPO_DIR}#g" "$REPO_DIR/deploy/systemd/coding-factory.service" \
  | sudo tee "/etc/systemd/system/${UNIT_NAME}.service" >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable --now "${UNIT_NAME}.service"
echo ">> started ${UNIT_NAME}; follow logs with: journalctl -u ${UNIT_NAME} -f"
