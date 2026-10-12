import json
from dataclasses import dataclass
from pathlib import Path

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.contract import Contract
from web3.logs import DISCARD


# Minimal ABI containing only the official Identity Registry functions we use.
# An ABI is a machine-readable contract interface, not deployed bytecode.

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
    chain_id: int
    registry_address: str
    agent_id: int

    @property
    def registry(self) -> str:
        return f"eip155:{self.chain_id}:{self.registry_address}"

    def __str__(self) -> str:
        return f"{self.registry}/{self.agent_id}"


@dataclass(frozen=True, slots=True)
class RegisteredAgent:

    identity: AgentIdentity
    owner: str
    agent_wallet: str
    agent_uri: str


@dataclass(frozen=True, slots=True)
class LocalDeployment:

    rpc_url: str
    chain_id: int
    identity_registry: str
    implementation: str
    owner: str
    version: str
    erc8004_commit: str

    @classmethod
    def from_path(cls, path: Path | str) -> "LocalDeployment":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            rpc_url=str(data["rpcUrl"]),
            chain_id=int(data["chainId"]),
            identity_registry=str(data["identityRegistry"]),
            implementation=str(data["implementation"]),
            owner=str(data["owner"]),
            version=str(data["version"]),
            erc8004_commit=str(data["erc8004Commit"]),
        )


class IdentityRegistryClient:
    """Read and write one deployed ERC-8004 Identity Registry contract."""

    def __init__(
        self,
        deployment: LocalDeployment,
        *,
        private_key: str | None = None,
    ) -> None:
        self.deployment = deployment
        self._account: LocalAccount | None = (
            Account.from_key(private_key) if private_key is not None else None
        )

        # Connect Python to the local Hardhat blockchain
        self.web3 = Web3(Web3.HTTPProvider(deployment.rpc_url))

        if not self.web3.is_connected():
            raise ConnectionError(
                f"cannot connect to EVM RPC at {deployment.rpc_url}"
            )

        # Make sure we connected to the expected blockchain.
        actual_chain_id = self.web3.eth.chain_id

        if actual_chain_id != deployment.chain_id:
            raise RuntimeError(
                f"deployment says chain {deployment.chain_id} but the RPC reports {actual_chain_id}"
            )

        # The proxy address is the address clients interact with.
        registry_address = self.web3.to_checksum_address(
            deployment.identity_registry
        )

        if not self.web3.eth.get_code(registry_address):
            raise RuntimeError(
                f"no contract code exists at Identity Registry {registry_address}"
            )

        # Create a Python interface to the Identity Registry contract.
        self.contract: Contract = self.web3.eth.contract(
            address=registry_address,
            abi=IDENTITY_REGISTRY_ABI,
        )


    @property
    def signer_address(self) -> str:
        if self._account is None:
            raise RuntimeError("a private key is required for registry writes")
        return self._account.address


    def _send_transaction(self, contract_function) -> tuple[str, object]:
        """Sign locally instead of relying on an unlocked RPC account."""

        if self._account is None:
            raise RuntimeError("a private key is required for registry writes")

        transaction = contract_function.build_transaction(
            {
                "from": self._account.address,
                "chainId": self.deployment.chain_id,
                "nonce": self.web3.eth.get_transaction_count(
                    self._account.address, "pending"
                ),
                "gasPrice": self.web3.eth.gas_price,
            }
        )
        signed = self._account.sign_transaction(transaction)
        tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
        return self.web3.to_hex(tx_hash), receipt


    def register(self) -> tuple[AgentIdentity, str]:
        """Register a new agent and return its identity and transaction hash."""
        tx_hash, receipt = self._send_transaction(self.contract.functions.register())
        if receipt.status != 1:
            raise RuntimeError(
                "ERC-8004 registration transaction reverted"
            )

        # register() emits a Registered event containing the assigned agentId.
        events = self.contract.events.Registered().process_receipt(
            receipt,
            errors=DISCARD,
        )

        if len(events) != 1:
            raise RuntimeError(
                "expected exactly one ERC-8004 Registered event"
            )

        identity = AgentIdentity(
            chain_id=self.deployment.chain_id,
            registry_address=str(self.contract.address),
            agent_id=int(events[0]["args"]["agentId"]),
        )

        return identity, tx_hash


    def set_agent_uri(self, agent_id: int, uri: str) -> str:
        """Store the off-chain registration-document URI for an agent."""
        tx_hash, receipt = self._send_transaction(
            self.contract.functions.setAgentURI(agent_id, uri)
        )
        if receipt.status != 1:
            raise RuntimeError("setAgentURI transaction reverted")

        return tx_hash

    def owner_of(self, agent_id: int) -> str:
        return str(self.contract.functions.ownerOf(agent_id).call())

    def token_uri(self, agent_id: int) -> str:
        return str(self.contract.functions.tokenURI(agent_id).call())

    def agent_wallet(self, agent_id: int) -> str:
        return str(self.contract.functions.getAgentWallet(agent_id).call())

    def version(self) -> str:
        return str(self.contract.functions.getVersion().call())

    def read_agent(self, agent_id: int) -> RegisteredAgent:
        """Read the useful identity fields for one registered agent."""
        identity = AgentIdentity(
            chain_id=self.deployment.chain_id,
            registry_address=str(self.contract.address),
            agent_id=agent_id,
        )
        return RegisteredAgent(
            identity=identity,
            owner=self.owner_of(agent_id),
            agent_wallet=self.agent_wallet(agent_id),
            agent_uri=self.token_uri(agent_id),
        )
