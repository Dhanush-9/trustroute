"""Validate TrustRoute evidence and its referenced x402 token settlement."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from web3 import Web3
from web3.logs import DISCARD

from erc8004.identity import LocalDeployment, RegisteredAgent
from erc8004.reputation import FeedbackRecord
from x402_support.network import PaymentNetwork


EVIDENCE_SCHEMA = "urn:trustroute:interaction-evidence:v2"

TOKEN_SETTLEMENT_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "from", "type": "address"},
            {"indexed": True, "name": "to", "type": "address"},
            {"indexed": False, "name": "value", "type": "uint256"},
        ],
        "name": "Transfer",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "authorizer", "type": "address"},
            {"indexed": True, "name": "nonce", "type": "bytes32"},
        ],
        "name": "AuthorizationUsed",
        "type": "event",
    },
]

TRANSFER_WITH_AUTHORIZATION_SIGNATURE = (
    "transferWithAuthorization(address,address,uint256,uint256,uint256,"
    "bytes32,uint8,bytes32,bytes32)"
)


class EvidenceVerificationError(ValueError):
    """Evidence cannot prove the claimed paid interaction."""


@dataclass(frozen=True, slots=True)
class VerifiedInteraction:
    """The unique payment transaction accepted for one feedback record."""

    payment_transaction: str
    amount_atomic: int


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceVerificationError(message)


def _object(data: dict, field: str) -> dict:
    value = data.get(field)
    if not isinstance(value, dict):
        raise EvidenceVerificationError(f"evidence field {field!r} is missing")
    return value


def _string(data: dict, field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise EvidenceVerificationError(f"evidence field {field!r} is missing")
    return value


def _checksum(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise EvidenceVerificationError(
            f"evidence field {field!r} is not an address"
        )
    try:
        return Web3.to_checksum_address(value)
    except ValueError as error:
        raise EvidenceVerificationError(
            f"evidence field {field!r} is not an address"
        ) from error


def _bytes32(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise EvidenceVerificationError(
            f"evidence field {field!r} is not bytes32"
        )
    try:
        raw = Web3.to_bytes(hexstr=value)
    except (TypeError, ValueError) as error:
        raise EvidenceVerificationError(
            f"evidence field {field!r} is not bytes32"
        ) from error
    if len(raw) != 32:
        raise EvidenceVerificationError(f"evidence field {field!r} is not bytes32")
    return Web3.to_hex(raw)


def load_local_evidence(
    feedback_uri: str,
    expected_hash: str,
    evidence_root: Path,
) -> dict:
    """Load only a content-matching JSON file inside the configured directory."""

    parsed = urlsplit(feedback_uri)
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        raise EvidenceVerificationError("evidence URI is not a local file URI")

    root = evidence_root.resolve()
    path = Path(unquote(parsed.path)).resolve()
    if not path.is_relative_to(root):
        raise EvidenceVerificationError(
            "evidence file is outside the configured directory"
        )

    try:
        content = path.read_bytes()
    except OSError as error:
        raise EvidenceVerificationError("evidence file cannot be read") from error

    actual_hash = Web3.to_hex(Web3.keccak(content))
    if actual_hash.lower() != _bytes32(expected_hash, "feedbackHash").lower():
        raise EvidenceVerificationError("evidence content hash does not match feedback")

    try:
        document = json.loads(content)
    except json.JSONDecodeError as error:
        raise EvidenceVerificationError("evidence file is not valid JSON") from error
    if not isinstance(document, dict):
        raise EvidenceVerificationError("evidence must be a JSON object")
    return document


class InteractionEvidenceVerifier:
    """Check evidence fields and the referenced EIP-3009 settlement on-chain."""

    def __init__(
        self,
        deployment: LocalDeployment,
        network: PaymentNetwork,
        evidence_root: Path,
    ) -> None:
        if deployment.chain_id != network.chain_id:
            raise ValueError("identity and payment deployments use different chains")
        self.deployment = deployment
        self.network = network
        self.evidence_root = evidence_root
        self.web3 = Web3(Web3.HTTPProvider(network.rpc_url))
        if (
            not self.web3.is_connected()
            or self.web3.eth.chain_id != network.chain_id
        ):
            raise ConnectionError("cannot connect to the expected payment network")
        if not self.web3.eth.get_code(network.asset):
            raise RuntimeError("configured payment asset has no contract code")
        self.token = self.web3.eth.contract(
            address=network.asset,
            abi=TOKEN_SETTLEMENT_ABI,
        )
        self.transfer_selector = Web3.keccak(
            text=TRANSFER_WITH_AUTHORIZATION_SIGNATURE
        )[:4]

    def verify(
        self,
        record: FeedbackRecord,
        agent: RegisteredAgent,
    ) -> VerifiedInteraction:
        """Return the proven settlement or raise a concise rejection reason."""

        document = load_local_evidence(
            record.feedback_uri,
            record.feedback_hash,
            self.evidence_root,
        )
        self._verify_feedback_fields(document, record, agent)
        return self._verify_payment(document, record, agent)

    def _verify_feedback_fields(
        self,
        document: dict,
        record: FeedbackRecord,
        agent: RegisteredAgent,
    ) -> None:
        expected_client = (
            f"eip155:{self.deployment.chain_id}:"
            f"{Web3.to_checksum_address(record.client_address)}"
        )
        _expect(
            document.get("$schema") == EVIDENCE_SCHEMA,
            "unknown evidence schema",
        )
        _expect(
            str(document.get("agentRegistry", "")).lower()
            == agent.identity.registry.lower(),
            "evidence registry does not match the agent identity",
        )
        _expect(
            document.get("agentId") == record.agent_id,
            "evidence agent ID differs",
        )
        _expect(
            str(document.get("clientAddress", "")).lower()
            == expected_client.lower(),
            "evidence client does not match the feedback reviewer",
        )
        _expect(document.get("value") == record.value, "evidence score differs")
        _expect(
            document.get("valueDecimals") == record.value_decimals,
            "evidence score precision differs",
        )
        _expect(document.get("tag1") == record.tag1, "evidence tag1 differs")
        _expect(document.get("tag2") == record.tag2, "evidence task type differs")
        _expect(
            document.get("endpoint") == record.endpoint,
            "evidence endpoint differs",
        )

        a2a = _object(document, "a2a")
        _expect(a2a.get("taskType") == record.tag2, "A2A task type differs")
        _string(a2a, "contextId")
        _string(a2a, "taskId")
        skills = a2a.get("skills")
        _expect(
            isinstance(skills, list)
            and bool(skills)
            and all(isinstance(item, str) and item for item in skills),
            "A2A skill evidence is missing",
        )

        trustroute = _object(document, "trustRoute")
        skill_id = _string(trustroute, "agentSkillId")
        _expect(skill_id in skills, "agent skill and A2A skill evidence differ")
        _expect(
            _checksum(trustroute.get("agentWallet"), "agentWallet").lower()
            == agent.agent_wallet.lower(),
            "evidence agent wallet differs from ERC-8004",
        )
        _bytes32(trustroute.get("requestHash"), "requestHash")
        _bytes32(trustroute.get("responseHash"), "responseHash")

    def _verify_payment(
        self,
        document: dict,
        record: FeedbackRecord,
        agent: RegisteredAgent,
    ) -> VerifiedInteraction:
        payment = _object(document, "proofOfPayment")
        _expect(payment.get("x402Version") == 2, "x402 version differs")
        _expect(payment.get("scheme") == "exact", "x402 scheme differs")
        payer = _checksum(payment.get("fromAddress"), "fromAddress")
        recipient = _checksum(payment.get("toAddress"), "toAddress")
        asset = _checksum(payment.get("asset"), "asset")
        _expect(
            payer.lower() == record.client_address.lower(),
            "reviewer was not payer",
        )
        _expect(
            recipient.lower() == agent.agent_wallet.lower(),
            "agent was not recipient",
        )
        _expect(
            payer.lower()
            not in {agent.owner.lower(), agent.agent_wallet.lower()},
            "agent owner or wallet cannot verify its own feedback",
        )
        _expect(asset.lower() == self.network.asset.lower(), "payment asset differs")
        _expect(
            payment.get("network") == self.network.network,
            "payment network differs",
        )
        _expect(
            str(payment.get("chainId", "")) == str(self.network.chain_id),
            "payment chain differs",
        )

        amount_text = str(payment.get("amountAtomic", ""))
        _expect(
            amount_text.isdigit() and int(amount_text) > 0,
            "payment amount is invalid",
        )
        amount = int(amount_text)
        transaction_hash = _bytes32(payment.get("txHash"), "txHash")

        try:
            receipt = self.web3.eth.get_transaction_receipt(transaction_hash)
            transaction = self.web3.eth.get_transaction(transaction_hash)
        except Exception as error:
            raise EvidenceVerificationError(
                "payment transaction does not exist"
            ) from error

        _expect(int(receipt["status"]) == 1, "payment transaction failed")
        _expect(
            int(receipt["blockNumber"]) <= record.block_number,
            "payment happened after feedback",
        )
        transaction_to = transaction.get("to")
        _expect(
            isinstance(transaction_to, str)
            and transaction_to.lower() == self.network.asset.lower(),
            "payment transaction did not call the configured token",
        )
        transaction_input = bytes(transaction.get("input", b""))
        _expect(
            transaction_input[:4] == self.transfer_selector,
            "payment did not use transferWithAuthorization",
        )

        transfers = self.token.events.Transfer().process_receipt(
            receipt,
            errors=DISCARD,
        )
        matching_transfers = [
            event
            for event in transfers
            if event["args"]["from"].lower() == payer.lower()
            and event["args"]["to"].lower() == recipient.lower()
            and int(event["args"]["value"]) == amount
        ]
        _expect(len(matching_transfers) == 1, "matching token transfer was not found")

        authorizations = self.token.events.AuthorizationUsed().process_receipt(
            receipt,
            errors=DISCARD,
        )
        matching_authorizations = [
            event
            for event in authorizations
            if event["args"]["authorizer"].lower() == payer.lower()
        ]
        _expect(
            len(matching_authorizations) == 1,
            "matching EIP-3009 authorization was not found",
        )
        return VerifiedInteraction(
            payment_transaction=transaction_hash,
            amount_atomic=amount,
        )
