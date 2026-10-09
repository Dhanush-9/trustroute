/* Deploy the official ERC-8004 Identity Registry */

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
// 9. Read and Save deployment information
// --------------------------------------------------

const chainId = await publicClient.getChainId();
const registryVersion = await identityRegistry.read.getVersion();

const deploymentInformation = {
  rpcUrl: "http://127.0.0.1:8545",
  chainId,
  identityRegistry: proxy.address,
  implementation: identityRegistryImpl.address,
  owner: deployerWallet.account.address,
  version: registryVersion,
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
