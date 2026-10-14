/* Deploy and fund the local x402 payment asset. */

import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { network } from "hardhat";
import { getAddress } from "viem";

const deploymentPath = process.env.TRUSTROUTE_X402_OUTPUT;

if (!deploymentPath) {
  throw new Error("TRUSTROUTE_X402_OUTPUT is required");
}

const connection = await network.connect();
const publicClient = await connection.viem.getPublicClient();
const wallets = await connection.viem.getWalletClients();

if (wallets.length < 5) {
  throw new Error("The local node must expose at least five development accounts");
}

// The payer signs authorizations, the recipient earns tokens, and the
// facilitator submits the transfer transaction and pays its gas.
// Use EIP-55 checksummed addresses because web3.py deliberately rejects
// lower-case address arguments when constructing contract calls.
const agentOwners = [
  getAddress(wallets[0].account.address),
  getAddress(wallets[3].account.address),
  getAddress(wallets[4].account.address),
];
const payer = getAddress(wallets[1].account.address);
const facilitator = getAddress(wallets[2].account.address);
const chainId = await publicClient.getChainId();

// Hardhat funds its development accounts with native gas currency. Check the
// roles that submit transactions so a changed node configuration fails
// during setup rather than during registration or settlement.
for (const owner of agentOwners) {
  if (await publicClient.getBalance({ address: owner }) === 0n) {
    throw new Error(`Local agent owner ${owner} has no native gas balance`);
  }
}
if (await publicClient.getBalance({ address: facilitator }) === 0n) {
  throw new Error("The local facilitator has no native gas balance");
}

const token = await connection.viem.deployContract("TrustRouteMockUSDC", [
  payer,
  100_000_000n, // 100.000000 trUSDC
]);

const paymentNetwork = {
  rpcUrl: "http://127.0.0.1:8545",
  chainId,
  network: `eip155:${chainId}`,
  asset: getAddress(token.address),
  assetName: "TrustRoute USD Coin",
  assetSymbol: "trUSDC",
  assetVersion: "2",
  assetDecimals: 6,
};

await mkdir(dirname(deploymentPath), { recursive: true });
await writeFile(
  deploymentPath,
  JSON.stringify(paymentNetwork, null, 2) + "\n",
  "utf8",
);

console.log("Local demo roles:");
console.log(`  generalist owner / recipient: ${agentOwners[0]}`);
console.log(`  translator owner / recipient: ${agentOwners[1]}`);
console.log(`  coder owner / recipient: ${agentOwners[2]}`);
console.log(`  payer funded with trUSDC: ${payer}`);
console.log(`  facilitator funded with gas: ${facilitator}`);
console.log("Payment network:");
console.log(JSON.stringify(paymentNetwork, null, 2));
