"""Create interaction evidence and submit optional ERC-8004 feedback."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from web3 import Web3

from client.config import ClientPaymentPolicy
from client.invocation import InvocationPlan, PaidInvocation
from erc8004.identity import LocalDeployment
from erc8004.reputation import FeedbackRecord, ReputationRegistryClient
from reputation import QUALITY_TAG
from reputation.evidence import EVIDENCE_SCHEMA, load_local_evidence


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    """Exact local bytes referenced and committed by one feedback event."""

    path: Path
    uri: str
    content_hash: str


def prepare_reviewer(
    deployment: LocalDeployment,
    policy: ClientPaymentPolicy,
    private_key: str,
) -> ReputationRegistryClient:
    """Validate feedback infrastructure before the paid interaction begins."""

    client = ReputationRegistryClient(deployment, private_key=private_key)
    if client.signer_address.lower() != policy.payer.lower():
        raise ValueError(
            "feedback signer must match the payer configured by the client policy"
        )
    return client


def _content_hash(text: str) -> str:
    return Web3.to_hex(Web3.keccak(text=text))


def _evidence_document(
    plan: InvocationPlan,
    invocation: PaidInvocation,
    source: str,
    score: int,
    reviewer: str,
) -> dict:
    entry = plan.entry
    payment = invocation.payment
    a2a = invocation.a2a
    return {
        "$schema": EVIDENCE_SCHEMA,
        "agentRegistry": entry.agent.identity.registry,
        "agentId": entry.agent.identity.agent_id,
        "clientAddress": (
            f"eip155:{plan.network.chain_id}:"
            f"{Web3.to_checksum_address(reviewer)}"
        ),
        "createdAt": datetime.now(timezone.utc).isoformat().replace(
            "+00:00",
            "Z",
        ),
        "value": score,
        "valueDecimals": 0,
        "tag1": QUALITY_TAG,
        "tag2": plan.task_type,
        "endpoint": a2a.interface_url,
        "a2a": {
            "taskType": plan.task_type,
            "skills": [entry.skill_id],
            "contextId": a2a.context_id,
            "taskId": a2a.task_id,
        },
        "proofOfPayment": {
            "x402Version": payment.x402_version,
            "scheme": payment.scheme,
            "fromAddress": payment.payer,
            "toAddress": payment.recipient,
            "chainId": str(plan.network.chain_id),
            "txHash": payment.transaction,
            "network": payment.network,
            "asset": payment.asset,
            "amountAtomic": payment.amount_atomic,
        },
        "trustRoute": {
            "agentSkillId": entry.skill_id,
            "agentWallet": entry.agent.agent_wallet,
            "agentURI": entry.agent.agent_uri,
            "agentCard": a2a.agent_card_url,
            "requestHash": _content_hash(source),
            "responseHash": _content_hash(a2a.response),
            "clientObservedLatencyMs": a2a.latency_ms,
        },
    }


def _write_evidence(document: dict, output_dir: Path) -> EvidenceArtifact:
    """Write deterministic JSON under its own Keccak-256 content hash."""

    content = (
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    content_hash = Web3.to_hex(Web3.keccak(content))
    resolved_dir = output_dir.resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True)
    path = resolved_dir / f"{content_hash}.json"

    if path.exists() and path.read_bytes() != content:
        raise RuntimeError("evidence hash collision with different local content")
    path.write_bytes(content)
    artifact = EvidenceArtifact(
        path=path,
        uri=path.as_uri(),
        content_hash=content_hash,
    )
    load_local_evidence(artifact.uri, artifact.content_hash, resolved_dir)
    return artifact


def submit_interaction_feedback(
    registry: ReputationRegistryClient,
    plan: InvocationPlan,
    invocation: PaidInvocation,
    source: str,
    score: int,
    evidence_dir: Path,
) -> tuple[EvidenceArtifact, FeedbackRecord]:
    """Bind one quality score to the paid A2A interaction and publish it."""

    if not 0 <= score <= 100:
        raise ValueError("feedback score must be between 0 and 100")

    entry = plan.entry
    payment = invocation.payment
    reviewer = registry.signer_address
    if reviewer.lower() != payment.payer.lower():
        raise ValueError("feedback reviewer is not the x402 payer")
    if reviewer.lower() == entry.agent.owner.lower():
        raise ValueError("an ERC-8004 agent owner cannot review its own agent")
    if payment.recipient.lower() != entry.agent.agent_wallet.lower():
        raise ValueError("payment recipient no longer matches the agentWallet")
    if payment.amount_atomic != entry.price.amount_atomic:
        raise ValueError("settled amount no longer matches the selected skill price")

    document = _evidence_document(
        plan,
        invocation,
        source,
        score,
        reviewer,
    )
    evidence = _write_evidence(document, evidence_dir)
    record = registry.give_feedback(
        agent_id=entry.agent.identity.agent_id,
        value=score,
        value_decimals=0,
        tag1=QUALITY_TAG,
        tag2=plan.task_type,
        endpoint=invocation.a2a.interface_url,
        feedback_uri=evidence.uri,
        feedback_hash=evidence.content_hash,
    )

    print(f"Reputation Registry: {registry.contract.address}")
    print(f"Agent ID: {record.agent_id}")
    print(f"Reviewer and x402 payer: {record.client_address}")
    print(f"Quality score: {record.value}/100")
    print(f"Feedback tags: {record.tag1} / {record.tag2}")
    print(f"A2A context ID: {invocation.a2a.context_id}")
    print(f"A2A task ID: {invocation.a2a.task_id}")
    print(f"x402 settlement: {invocation.payment.transaction}")
    print(f"Evidence file: {evidence.path}")
    print(f"Evidence hash: {evidence.content_hash}")
    print(f"Feedback transaction: {record.transaction_hash}")
    print(f"Feedback index: {record.feedback_index}")
    print("Contract read-back: verified")
    print("Meaning: paid interaction verified; quality claim not independently proven")

    return evidence, record
