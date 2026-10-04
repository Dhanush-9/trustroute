#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ERC_DIR="${PROJECT_DIR}/.cache/erc-8004-contracts"

if [[ ! -d "${ERC_DIR}/node_modules" ]]; then
  echo "Run scripts/setup_erc8004.sh first" >&2
  exit 1
fi

cd "${ERC_DIR}"
exec env \
  SEPOLIA_RPC_URL=http://127.0.0.1:8545 \
  MAINNET_RPC_URL=http://127.0.0.1:8545 \
  XDG_CONFIG_HOME="${PROJECT_DIR}/.cache/xdg-config" \
  XDG_CACHE_HOME="${PROJECT_DIR}/.cache/xdg-cache" \
  XDG_DATA_HOME="${PROJECT_DIR}/.cache/xdg-data" \
  npx hardhat node
