"""Calculate raw, task-typed, and interaction-verified reputation views."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from erc8004.identity import LocalDeployment, RegisteredAgent
from erc8004.reputation import FeedbackRecord, ReputationRegistryClient
from reputation import QUALITY_TAG
from reputation.evidence import (
    EvidenceVerificationError,
    InteractionEvidenceVerifier,
    VerifiedInteraction,
)
from x402_support.network import PaymentNetwork


@dataclass(frozen=True, slots=True)
class ReputationScore:
    """An average and the number of feedback records that contributed to it."""

    average: Decimal | None
    count: int


@dataclass(frozen=True, slots=True)
class RejectedFeedback:
    """One task-relevant record excluded from the verified view."""

    client_address: str
    feedback_index: int
    reason: str


@dataclass(frozen=True, slots=True)
class AgentReputation:
    """Three interpretations of the same agent feedback history."""

    raw: ReputationScore
    task_typed: ReputationScore
    interaction_verified: ReputationScore
    verification_rejections: tuple[RejectedFeedback, ...]


class EvidenceVerifier(Protocol):
    """Small interface that keeps aggregation independently repeatable."""

    def verify(
        self,
        record: FeedbackRecord,
        agent: RegisteredAgent,
    ) -> VerifiedInteraction: ...


def _quality_value(record: FeedbackRecord) -> Decimal | None:
    """Normalize an ERC-8004 fixed-point value to TrustRoute's 0-100 scale."""

    if record.is_revoked or record.tag1 != QUALITY_TAG:
        return None
    value = Decimal(record.value) / Decimal(10**record.value_decimals)
    return value if Decimal(0) <= value <= Decimal(100) else None


def _average(values: list[Decimal]) -> ReputationScore:
    if not values:
        return ReputationScore(average=None, count=0)
    return ReputationScore(
        average=sum(values, start=Decimal(0)) / Decimal(len(values)),
        count=len(values),
    )


def evaluate_reputation_records(
    records: tuple[FeedbackRecord, ...],
    agents: tuple[RegisteredAgent, ...],
    task_type: str,
    verifier: EvidenceVerifier,
) -> dict[int, AgentReputation]:
    """Apply all three policies to supplied records in blockchain order."""

    agents_by_id = {agent.identity.agent_id: agent for agent in agents}

    # Verify in blockchain order. The first valid feedback claiming a payment
    # receipt owns it; later reuse is rejected deterministically.
    verified_records: set[tuple[int, str, int]] = set()
    used_payments: set[str] = set()
    rejection_by_record: dict[tuple[int, str, int], str] = {}
    for record in records:
        if _quality_value(record) is None:
            continue
        key = (record.agent_id, record.client_address.lower(), record.feedback_index)
        try:
            interaction = verifier.verify(record, agents_by_id[record.agent_id])
            payment_key = interaction.payment_transaction.lower()
            if payment_key in used_payments:
                raise EvidenceVerificationError(
                    "payment receipt was already used by earlier feedback"
                )
        except EvidenceVerificationError as error:
            rejection_by_record[key] = str(error)
        else:
            used_payments.add(payment_key)
            verified_records.add(key)

    views: dict[int, AgentReputation] = {}
    for agent_id in agents_by_id:
        raw_values: list[Decimal] = []
        typed_values: list[Decimal] = []
        verified_values: list[Decimal] = []
        rejections: list[RejectedFeedback] = []

        for record in records:
            if record.agent_id != agent_id:
                continue
            value = _quality_value(record)
            if value is None:
                continue
            raw_values.append(value)
            if record.tag2 != task_type:
                continue
            typed_values.append(value)

            key = (
                record.agent_id,
                record.client_address.lower(),
                record.feedback_index,
            )
            if key in verified_records:
                verified_values.append(value)
            else:
                rejections.append(
                    RejectedFeedback(
                        client_address=record.client_address,
                        feedback_index=record.feedback_index,
                        reason=rejection_by_record.get(
                            key,
                            "interaction evidence was not verified",
                        ),
                    )
                )

        views[agent_id] = AgentReputation(
            raw=_average(raw_values),
            task_typed=_average(typed_values),
            interaction_verified=_average(verified_values),
            verification_rejections=tuple(rejections),
        )

    return views


def calculate_reputation_views(
    deployment: LocalDeployment,
    network: PaymentNetwork,
    agents: tuple[RegisteredAgent, ...],
    task_type: str,
    evidence_root: Path,
) -> dict[int, AgentReputation]:
    """Read live ERC-8004 feedback and apply the three reputation policies."""

    registry = ReputationRegistryClient(deployment)
    agent_ids = {agent.identity.agent_id for agent in agents}
    records = registry.feedback_records(agent_ids)
    verifier = InteractionEvidenceVerifier(deployment, network, evidence_root)
    return evaluate_reputation_records(records, agents, task_type, verifier)
