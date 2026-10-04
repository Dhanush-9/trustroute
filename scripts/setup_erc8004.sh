#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ERC_DIR="${PROJECT_DIR}/.cache/erc-8004-contracts"
COMMIT_VER="b9e466c250744a7e06b13dff9d3c2844ed64f825"

# Download the repository if we don't already have it
if [[ ! -d "${ERC_DIR}/.git" ]]; then
  git clone https://github.com/erc-8004/erc-8004-contracts.git "${ERC_DIR}"
fi

actual_commit="$(git -C "${ERC_DIR}" rev-parse HEAD)"
if [[ "${actual_commit}" != "${COMMIT_VER}" ]]; then
  git -C "${ERC_DIR}" fetch origin "${COMMIT_VER}"
  git -C "${ERC_DIR}" checkout --detach "${COMMIT_VER}"
fi

# Install JavaScript dependencies
npm --prefix "${ERC_DIR}" ci --legacy-peer-deps

# Compile the smart contracts
(
  cd "${ERC_DIR}"
  SEPOLIA_RPC_URL=http://127.0.0.1:8545 \
  MAINNET_RPC_URL=http://127.0.0.1:8545 \
  XDG_CONFIG_HOME="${PROJECT_DIR}/.cache/xdg-config" \
  XDG_CACHE_HOME="${PROJECT_DIR}/.cache/xdg-cache" \
  XDG_DATA_HOME="${PROJECT_DIR}/.cache/xdg-data" \
  npx hardhat compile
)

echo "ERC-8004 setup complete."
