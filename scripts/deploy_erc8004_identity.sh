#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ERC_DIR="${PROJECT_DIR}/.cache/erc-8004-contracts"
COMMIT_VER="b9e466c250744a7e06b13dff9d3c2844ed64f825"
temporary_script="${ERC_DIR}/scripts/trustroute-deploy-identity.ts"

if [[ ! -d "${ERC_DIR}/node_modules" ]]; then
  echo "Run scripts/setup_erc8004.sh first" >&2
  exit 1
fi

# Hardhat executes scripts in its own project, so copy our small deployment
# entry point into the ignored, pinned upstream checkout before running it.
cp "${PROJECT_DIR}/infra/erc8004/deploy_identity.ts" "${temporary_script}"

cd "${ERC_DIR}"
TRUSTROUTE_DEPLOYMENT_OUTPUT="${PROJECT_DIR}/var/identity-deployment.json" \
TRUSTROUTE_ERC8004_COMMIT="${COMMIT_VER}" \
SEPOLIA_RPC_URL=http://127.0.0.1:8545 \
MAINNET_RPC_URL=http://127.0.0.1:8545 \
XDG_CONFIG_HOME="${PROJECT_DIR}/.cache/xdg-config" \
XDG_CACHE_HOME="${PROJECT_DIR}/.cache/xdg-cache" \
XDG_DATA_HOME="${PROJECT_DIR}/.cache/xdg-data" \
npx hardhat run "${temporary_script}" --network localhost
