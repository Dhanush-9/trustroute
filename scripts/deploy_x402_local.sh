#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ERC_DIR="${PROJECT_DIR}/.cache/erc-8004-contracts"
temporary_script="${ERC_DIR}/scripts/trustroute-deploy-x402.ts"

if [[ ! -d "${ERC_DIR}/node_modules" ]]; then
  echo "Run scripts/setup_erc8004.sh first" >&2
  exit 1
fi

if [[ ! -f "${ERC_DIR}/artifacts/contracts/TrustRouteMockUSDC.sol/TrustRouteMockUSDC.json" ]]; then
  echo "The local payment contract is not compiled. Run scripts/setup_erc8004.sh again." >&2
  exit 1
fi

cp "${PROJECT_DIR}/infra/x402/deploy_x402.ts" "${temporary_script}"

cd "${ERC_DIR}"
TRUSTROUTE_X402_OUTPUT="${PROJECT_DIR}/var/payment-network.json" \
SEPOLIA_RPC_URL=http://127.0.0.1:8545 \
MAINNET_RPC_URL=http://127.0.0.1:8545 \
XDG_CONFIG_HOME="${PROJECT_DIR}/.cache/xdg-config" \
XDG_CACHE_HOME="${PROJECT_DIR}/.cache/xdg-cache" \
XDG_DATA_HOME="${PROJECT_DIR}/.cache/xdg-data" \
npx hardhat run "${temporary_script}" --network localhost
