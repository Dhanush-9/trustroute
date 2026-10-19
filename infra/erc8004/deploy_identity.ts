/* Deploy the official ERC-8004 Identity and Reputation registries */

import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { network } from "hardhat";
import { encodeFunctionData, zeroAddress } from "viem";

// ----------------------------------------------
// 1. Read configuration passed from shell script
// ----------------------------------------------

const deploymentPath = process.env.TRUSTROUTE_DEPLOYMENT_OUTPUT;
const erc8004Commit = process.env.TRUSTROUTE_ERC8004_COMMIT;

if (!deploymentPath || !erc8004Commit) {
  throw new Error("Deployment path and ERC-8004 commit are required");
}


// ----------------------------------------------
// 2. Connect to local Hardhat blockchain
// ----------------------------------------------

const hardhatConnection = await network.connect();

const publicClient = await hardhatConnection.viem.getPublicClient();

const walletClients = await hardhatConnection.viem.getWalletClients();
const deployerWallet = walletClients[0];


// ----------------------------------------------
// 3. Deploy the temporary UUPS implementation
// ----------------------------------------------

const temporaryImpl = 
    await hardhatConnection.viem.deployContract(
        "HardhatMinimalUUPS"
    );

//prepare the encoded initialize(...) call
const temporaryInitCall = encodeFunctionData({
    abi: temporaryImpl.abi,
    functionName: "initialize",
    args: [zeroAddress],
});


// ----------------------------------------------
// 4. Deploy the proxy
// ----------------------------------------------

const proxy = 
    await hardhatConnection.viem.deployContract(
        "ERC1967Proxy", 
        [
            temporaryImpl.address,
            temporaryInitCall,
        ]
    );


// ----------------------------------------------
// 5. Deploy the real ERC-8004 Identity Registry
// ----------------------------------------------

const identityRegistryImpl = 
    await hardhatConnection.viem.deployContract(
        "IdentityRegistryUpgradeable"
    );


// ----------------------------------------------
// 6. Talk to proxy using temporary UUPS interface
// ----------------------------------------------

const proxyAsTemporaryContract = 
    await hardhatConnection.viem.getContractAt(
        "HardhatMinimalUUPS",
        proxy.address
    );

const identityRegistryInitCall = encodeFunctionData({
    abi: identityRegistryImpl.abi,
    functionName: "initialize",
});

// ----------------------------------------------
// 7. Upgrade the proxy to real Identity Registry
// ----------------------------------------------

const upgradeTransactionHash = 
    await proxyAsTemporaryContract.write.upgradeToAndCall([
        identityRegistryImpl.address,
        identityRegistryInitCall,
    ]);

await publicClient.waitForTransactionReceipt({
    hash: upgradeTransactionHash, 
});

// --------------------------------------------------
// 8. Treat the proxy as the real Identity Registry
// --------------------------------------------------

const identityRegistry = 
    await hardhatConnection.viem.getContractAt(
        "IdentityRegistryUpgradeable",
        proxy.address,
    );

// --------------------------------------------------
// 9. Deploy the Reputation Registry behind its proxy
// --------------------------------------------------

// The Reputation Registry is a separate ERC-8004 contract. Its initializer
// receives the Identity Registry address so it can reject owner self-feedback.
const reputationTemporaryImpl =
    await hardhatConnection.viem.deployContract(
        "HardhatMinimalUUPS"
    );

const reputationTemporaryInitCall = encodeFunctionData({
    abi: reputationTemporaryImpl.abi,
    functionName: "initialize",
    args: [identityRegistry.address],
});

const reputationProxy =
    await hardhatConnection.viem.deployContract(
        "ERC1967Proxy",
        [
            reputationTemporaryImpl.address,
            reputationTemporaryInitCall,
        ]
    );

const reputationRegistryImpl =
    await hardhatConnection.viem.deployContract(
        "ReputationRegistryUpgradeable"
    );

const reputationProxyAsTemporaryContract =
    await hardhatConnection.viem.getContractAt(
        "HardhatMinimalUUPS",
        reputationProxy.address
    );

const reputationRegistryInitCall = encodeFunctionData({
    abi: reputationRegistryImpl.abi,
    functionName: "initialize",
    args: [identityRegistry.address],
});

const reputationUpgradeTransactionHash =
    await reputationProxyAsTemporaryContract.write.upgradeToAndCall([
        reputationRegistryImpl.address,
        reputationRegistryInitCall,
    ]);

await publicClient.waitForTransactionReceipt({
    hash: reputationUpgradeTransactionHash,
});

const reputationRegistry =
    await hardhatConnection.viem.getContractAt(
        "ReputationRegistryUpgradeable",
        reputationProxy.address,
    );

// --------------------------------------------------
// 10. Read and save deployment information
// --------------------------------------------------

const chainId = await publicClient.getChainId();
const identityVersion = await identityRegistry.read.getVersion();
const reputationVersion = await reputationRegistry.read.getVersion();
const linkedIdentityRegistry = await reputationRegistry.read.getIdentityRegistry();

if (linkedIdentityRegistry.toLowerCase() !== identityRegistry.address.toLowerCase()) {
  throw new Error("Reputation Registry is linked to the wrong Identity Registry");
}

// No agents can be registered before deployment completes. Starting the event
// scans here avoids searching unrelated historical blocks on a persistent RPC.
const deploymentBlock = await publicClient.getBlockNumber();

const deploymentInformation = {
  rpcUrl: "http://127.0.0.1:8545",
  chainId,
  deploymentBlock: Number(deploymentBlock),
  identityRegistry: proxy.address,
  implementation: identityRegistryImpl.address,
  reputationRegistry: reputationProxy.address,
  reputationImplementation: reputationRegistryImpl.address,
  owner: deployerWallet.account.address,
  version: identityVersion,
  reputationVersion,
  erc8004Commit,
};

await mkdir(
    dirname(deploymentPath), 
    { recursive: true }
);

await writeFile(
    deploymentPath,
    JSON.stringify(deploymentInformation, null, 2) + "\n", 
    "utf8"
);

console.log(
    JSON.stringify(deploymentInformation, null, 2)
);
