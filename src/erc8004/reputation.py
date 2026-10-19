"""Minimal client for the official ERC-8004 Reputation Registry."""

from __future__ import annotations

from dataclasses import dataclass

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.contract import Contract
from web3.logs import DISCARD

from erc8004.identity import LocalDeployment


REPUTATION_REGISTRY_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "agentId", "type": "uint256"},
            {"indexed": True, "name": "clientAddress", "type": "address"},
            {"indexed": False, "name": "feedbackIndex", "type": "uint64"},
            {"indexed": False, "name": "value", "type": "int128"},
            {"indexed": False, "name": "valueDecimals", "type": "uint8"},
            {"indexed": True, "name": "indexedTag1", "type": "string"},
            {"indexed": False, "name": "tag1", "type": "string"},
            {"indexed": False, "name": "tag2", "type": "string"},
            {"indexed": False, "name": "endpoint", "type": "string"},
            {"indexed": False, "name": "feedbackURI", "type": "string"},
            {"indexed": False, "name": "feedbackHash", "type": "bytes32"},
        ],
        "name": "NewFeedback",
        "type": "event",
    },
    {
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "value", "type": "int128"},
            {"name": "valueDecimals", "type": "uint8"},
            {"name": "tag1", "type": "string"},
            {"name": "tag2", "type": "string"},
            {"name": "endpoint", "type": "string"},
            {"name": "feedbackURI", "type": "string"},
            {"name": "feedbackHash", "type": "bytes32"},
        ],
        "name": "giveFeedback",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getIdentityRegistry",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "clientAddress", "type": "address"},
        ],
        "name": "getLastIndex",
        "outputs": [{"name": "", "type": "uint64"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "clientAddress", "type": "address"},
            {"name": "feedbackIndex", "type": "uint64"},
        ],
        "name": "readFeedback",
        "outputs": [
            {"name": "value", "type": "int128"},
            {"name": "valueDecimals", "type": "uint8"},
            {"name": "tag1", "type": "string"},
            {"name": "tag2", "type": "string"},
            {"name": "isRevoked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


@dataclass(frozen=True, slots=True)
class FeedbackRecord:
    """One feedback record confirmed by both event and contract read-back."""

    transaction_hash: str
    agent_id: int
    client_address: str
    feedback_index: int
    value: int
    value_decimals: int
    tag1: str
    tag2: str
    endpoint: str
    feedback_uri: str
    feedback_hash: str
    is_revoked: bool


class ReputationRegistryClient:
    """Submit and read feedback against one deployed Reputation Registry."""

    def __init__(self, deployment: LocalDeployment, *, private_key: str) -> None:
        if deployment.reputation_registry is None:
            raise RuntimeError(
                "deployment has no Reputation Registry; redeploy ERC-8004 registries"
            )

        self.deployment = deployment
        self._account: LocalAccount = Account.from_key(private_key)
        self.web3 = Web3(Web3.HTTPProvider(deployment.rpc_url))
        if not self.web3.is_connected():
            raise ConnectionError(
                f"cannot connect to EVM RPC at {deployment.rpc_url}"
            )
        if self.web3.eth.chain_id != deployment.chain_id:
            raise RuntimeError("Reputation Registry RPC is on the wrong chain")

        registry_address = self.web3.to_checksum_address(
            deployment.reputation_registry
        )
        if not self.web3.eth.get_code(registry_address):
            raise RuntimeError(
                f"no contract code exists at Reputation Registry {registry_address}"
            )

        self.contract: Contract = self.web3.eth.contract(
            address=registry_address,
            abi=REPUTATION_REGISTRY_ABI,
        )
        linked_identity = self.contract.functions.getIdentityRegistry().call()
        if linked_identity.lower() != deployment.identity_registry.lower():
            raise RuntimeError(
                "Reputation Registry is linked to a different Identity Registry"
            )

    @property
    def signer_address(self) -> str:
        return self._account.address

    def last_index(self, agent_id: int, client_address: str) -> int:
        """Return how many feedback records this client submitted to an agent."""

        return int(
            self.contract.functions.getLastIndex(
                agent_id,
                Web3.to_checksum_address(client_address),
            ).call()
        )

    def give_feedback(
        self,
        *,
        agent_id: int,
        value: int,
        value_decimals: int,
        tag1: str,
        tag2: str,
        endpoint: str,
        feedback_uri: str,
        feedback_hash: str,
    ) -> FeedbackRecord:
        """Sign, submit, and read back one ERC-8004 feedback record."""

        if agent_id < 0:
            raise ValueError("agent ID must not be negative")
        if not 0 <= value_decimals <= 18:
            raise ValueError("feedback valueDecimals must be between 0 and 18")

        hash_bytes = Web3.to_bytes(hexstr=feedback_hash)
        if len(hash_bytes) != 32:
            raise ValueError("feedback hash must contain exactly 32 bytes")

        contract_function = self.contract.functions.giveFeedback(
            agent_id,
            value,
            value_decimals,
            tag1,
            tag2,
            endpoint,
            feedback_uri,
            hash_bytes,
        )
        transaction = contract_function.build_transaction(
            {
                "from": self._account.address,
                "chainId": self.deployment.chain_id,
                "nonce": self.web3.eth.get_transaction_count(
                    self._account.address,
                    "pending",
                ),
                "gasPrice": self.web3.eth.gas_price,
            }
        )
        signed = self._account.sign_transaction(transaction)
        tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status != 1:
            raise RuntimeError("ERC-8004 giveFeedback transaction reverted")

        events = self.contract.events.NewFeedback().process_receipt(
            receipt,
            errors=DISCARD,
        )
        if len(events) != 1:
            raise RuntimeError("expected exactly one ERC-8004 NewFeedback event")

        event = events[0]["args"]
        feedback_index = int(event["feedbackIndex"])
        stored = self.contract.functions.readFeedback(
            agent_id,
            self._account.address,
            feedback_index,
        ).call()
        event_hash = Web3.to_hex(event["feedbackHash"])

        if (
            int(event["agentId"]) != agent_id
            or event["clientAddress"].lower() != self._account.address.lower()
            or int(event["value"]) != value
            or int(event["valueDecimals"]) != value_decimals
            or event["tag1"] != tag1
            or event["tag2"] != tag2
            or event["endpoint"] != endpoint
            or event["feedbackURI"] != feedback_uri
            or int(stored[0]) != value
            or int(stored[1]) != value_decimals
            or stored[2] != tag1
            or stored[3] != tag2
            or bool(stored[4])
            or event_hash.lower() != feedback_hash.lower()
        ):
            raise RuntimeError("feedback event and contract read-back differ")

        return FeedbackRecord(
            transaction_hash=self.web3.to_hex(tx_hash),
            agent_id=agent_id,
            client_address=str(event["clientAddress"]),
            feedback_index=feedback_index,
            value=int(stored[0]),
            value_decimals=int(stored[1]),
            tag1=str(stored[2]),
            tag2=str(stored[3]),
            endpoint=str(event["endpoint"]),
            feedback_uri=str(event["feedbackURI"]),
            feedback_hash=event_hash,
            is_revoked=bool(stored[4]),
        )
