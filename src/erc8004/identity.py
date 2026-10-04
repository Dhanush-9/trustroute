"""Minimal client for the official ERC-8004 Identity Registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from web3 import Web3
from web3.contract import Contract
from web3.logs import DISCARD


# A small ABI is easier to audit than loading the complete build artifact. Each
# entry below corresponds to a function or event used by this checkpoint.
IDENTITY_REGISTRY_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "agentId", "type": "uint256"},
            {"indexed": False, "name": "agentURI", "type": "string"},
            {"indexed": True, "name": "owner", "type": "address"},
        ],
        "name": "Registered",
        "type": "event",
    },
    {
        "inputs": [],
        "name": "register",
        "outputs": [{"name": "agentId", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "newURI", "type": "string"},
        ],
        "name": "setAgentURI",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "ownerOf",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "tokenURI",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "name": "getAgentWallet",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getVersion",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "pure",
        "type": "function",
    },
]


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    """The chain-qualified identity assigned by an ERC-8004 registry."""

    chain_id: int
    registry_address: str
    agent_id: int

    @property
    def registry(self) -> str:
        """Return the CAIP-2-style registry identifier used in the file."""

        return f"eip155:{self.chain_id}:{self.registry_address}"

    def __str__(self) -> str:
        return f"{self.registry}/{self.agent_id}"


@dataclass(frozen=True, slots=True)
class LocalDeployment:
    """Facts recorded when the local Identity Registry is deployed."""

    rpc_url: str
    chain_id: int
    identity_registry: str
    implementation: str
    owner: str
    version: str
    upstream_commit: str

    @classmethod
    def from_path(cls, path: Path | str) -> LocalDeployment:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            rpc_url=str(data["rpcUrl"]),
            chain_id=int(data["chainId"]),
            identity_registry=str(data["identityRegistry"]),
            implementation=str(data["implementation"]),
            owner=str(data["owner"]),
            version=str(data["version"]),
            upstream_commit=str(data["upstreamCommit"]),
        )


class IdentityRegistryClient:
    """Read and write one deployed ERC-8004 Identity Registry contract."""

    def __init__(self, deployment: LocalDeployment) -> None:
        self.deployment = deployment
        self.web3 = Web3(Web3.HTTPProvider(deployment.rpc_url))

        if not self.web3.is_connected():
            raise ConnectionError(f"cannot connect to EVM RPC at {deployment.rpc_url}")

        actual_chain_id = self.web3.eth.chain_id
        if actual_chain_id != deployment.chain_id:
            raise RuntimeError(
                f"deployment says chain {deployment.chain_id}, "
                f"but the RPC reports {actual_chain_id}"
            )

        registry_address = self.web3.to_checksum_address(
            deployment.identity_registry
        )
        if not self.web3.eth.get_code(registry_address):
            raise RuntimeError(
                f"no contract code exists at Identity Registry {registry_address}"
            )

        self.contract: Contract = self.web3.eth.contract(
            address=registry_address,
            abi=IDENTITY_REGISTRY_ABI,
        )

    @property
    def default_account(self) -> str:
        """Use Hardhat's first unlocked account for this local-only demo."""

        accounts = self.web3.eth.accounts
        if not accounts:
            raise RuntimeError("the RPC does not expose an unlocked local account")
        return accounts[0]

    def register(self) -> tuple[AgentIdentity, str]:
        """Mint an identity and recover its agent ID from the emitted event."""

        # We first register without a URI because the registry assigns agentId.
        # The caller can then write that real ID into the registration document.
        tx_hash = self.contract.functions.register().transact(
            {"from": self.default_account}
        )
        receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status != 1:
            raise RuntimeError("ERC-8004 registration transaction reverted")

        events = self.contract.events.Registered().process_receipt(
            receipt,
            errors=DISCARD,
        )
        if len(events) != 1:
            raise RuntimeError("expected exactly one ERC-8004 Registered event")

        identity = AgentIdentity(
            chain_id=self.deployment.chain_id,
            registry_address=str(self.contract.address),
            agent_id=int(events[0]["args"]["agentId"]),
        )
        return identity, self.web3.to_hex(tx_hash)

    def set_agent_uri(self, agent_id: int, uri: str) -> str:
        tx_hash = self.contract.functions.setAgentURI(agent_id, uri).transact(
            {"from": self.default_account}
        )
        receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status != 1:
            raise RuntimeError("setAgentURI transaction reverted")
        return self.web3.to_hex(tx_hash)

    def owner_of(self, agent_id: int) -> str:
        return str(self.contract.functions.ownerOf(agent_id).call())

    def token_uri(self, agent_id: int) -> str:
        return str(self.contract.functions.tokenURI(agent_id).call())

    def agent_wallet(self, agent_id: int) -> str:
        return str(self.contract.functions.getAgentWallet(agent_id).call())

    def version(self) -> str:
        return str(self.contract.functions.getVersion().call())
