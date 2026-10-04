/** Deploy the official ERC-8004 Identity Registry using its upstream pattern. */

import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { network } from "hardhat";
import { encodeFunctionData, zeroAddress } from "viem";

const outputPath = process.env.TRUSTROUTE_DEPLOYMENT_OUTPUT;
const upstreamCommit = process.env.TRUSTROUTE_ERC8004_COMMIT;

if (!outputPath || !upstreamCommit) {
  throw new Error(
    "TRUSTROUTE_DEPLOYMENT_OUTPUT and TRUSTROUTE_ERC8004_COMMIT are required",
  );
}

const { viem } = await network.connect();
const publicClient = await viem.getPublicClient();
const [owner] = await viem.getWalletClients();

// The official registry is UUPS-upgradeable. 
/* The proxy is created with the small upstream test implementation,
  then upgraded to the real registry and initialized atomically.
  Calls and durable state live at the proxy address. */

const minimal = await viem.deployContract("HardhatMinimalUUPS");
const minimalInit = encodeFunctionData({
  abi: minimal.abi,
  functionName: "initialize",
  args: [zeroAddress],
});

//create proxy and point to temporary implementation
const proxy = await viem.deployContract("ERC1967Proxy", [
  minimal.address,
  minimalInit,
]);

//real registry
const implementation = await viem.deployContract(
  "IdentityRegistryUpgradeable",
);
const minimalProxy = await viem.getContractAt(
  "HardhatMinimalUUPS",
  proxy.address,
);
const identityInit = encodeFunctionData({
  abi: implementation.abi,
  functionName: "initialize",
});
const upgradeHash = await minimalProxy.write.upgradeToAndCall([
  implementation.address,
  identityInit,
]);
await publicClient.waitForTransactionReceipt({ hash: upgradeHash });

const identity = await viem.getContractAt(
  "IdentityRegistryUpgradeable",
  proxy.address,
);
const chainId = await publicClient.getChainId();
const version = await identity.read.getVersion();

const deployment = {
  rpcUrl: "http://127.0.0.1:8545",
  chainId,
  identityRegistry: proxy.address,
  implementation: implementation.address,
  owner: owner.account.address,
  version,
  upstreamCommit,
};

await mkdir(dirname(outputPath), { recursive: true });
await writeFile(outputPath, JSON.stringify(deployment, null, 2) + "\n", "utf8");
console.log(JSON.stringify(deployment, null, 2));
