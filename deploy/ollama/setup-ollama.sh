#!/usr/bin/env bash
# setup-ollama.sh - install Ollama and pull a model for the coding-factory `llm`
# backend, so the agent runs on a self-hosted machine with no API key and no
# per-token cost.
#
# Usage:
#   ./deploy/ollama/setup-ollama.sh                 # default model: qwen2.5:3b
#   MODEL=qwen2.5-coder:7b ./deploy/ollama/setup-ollama.sh
#   OLLAMA_HOST=0.0.0.0 ./deploy/ollama/setup-ollama.sh   # expose on the LAN
#
# After it finishes, point the factory at Ollama:
#   export FACTORY_BACKEND=llm
#   export FACTORY_LLM_CHAIN=ollama
#   export OLLAMA_MODEL=qwen2.5:3b
set -euo pipefail

MODEL="qwen2.5:3b"

echo ">> installing Ollama"
if command -v ollama >/dev/null 2>&1; then
  echo "   ollama already installed"
else
  # Official install script (https://ollama.com/install.sh).
  curl -fsSL https://ollama.com/install.sh | sh
fi

echo ">> ensuring the ollama service is running"
if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl enable --now ollama 2>/dev/null || true
fi

echo ">> waiting for the API on 127.0.0.1:11434"
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo ">> pulling model: ${MODEL}"
ollama pull "${MODEL}"

echo
echo ">> ready. Verify with:"
echo "   ollama list"
echo "   curl -s http://127.0.0.1:11434/v1/models"
echo
echo ">> then run the factory with the Ollama backend:"
echo "   export FACTORY_BACKEND=llm"
echo "   export FACTORY_LLM_CHAIN=ollama"
echo "   export OLLAMA_MODEL=${MODEL}"
echo "   factory backends        # 'llm available=True'"
