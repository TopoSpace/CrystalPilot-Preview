#!/usr/bin/env bash
# Install the version verified with this repository's pinned Python SDK.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
npm install --prefix "$repo_root/vendor/codex" --no-audit --no-fund "@openai/codex@${1:-0.155.0}"
"$repo_root/vendor/codex/node_modules/.bin/codex" --version
