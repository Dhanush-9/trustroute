#!/usr/bin/env python3
"""Repeat the small four-record Checkpoint 4 reputation scenario."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from erc8004.identity import AgentIdentity, RegisteredAgent
from erc8004.reputation import FeedbackRecord
from reputation.evidence import EvidenceVerificationError, VerifiedInteraction
from reputation.views import evaluate_reputation_records


AGENT = RegisteredAgent(
    identity=AgentIdentity(
        chain_id=31337,
        registry_address="0x0000000000000000000000000000000000000001",
        agent_id=2,
    ),
    owner="0x0000000000000000000000000000000000000002",
    agent_wallet="0x0000000000000000000000000000000000000002",
    agent_uri="http://127.0.0.1:8006/registration.json",
)


def _record(
    block: int,
    reviewer: str,
    score: int,
    task_type: str,
) -> FeedbackRecord:
    return FeedbackRecord(
        transaction_hash=f"0x{block:064x}",
        block_number=block,
        log_index=0,
        agent_id=AGENT.identity.agent_id,
        client_address=reviewer,
        feedback_index=1,
        value=score,
        value_decimals=0,
        tag1="quality",
        tag2=task_type,
        endpoint="http://127.0.0.1:8006/",
        feedback_uri=f"file:///controlled/{block}.json",
        feedback_hash=f"0x{block:064x}",
        is_revoked=False,
    )


RECORDS = (
    _record(1, "0x0000000000000000000000000000000000000011", 85, "translation"),
    _record(2, "0x0000000000000000000000000000000000000012", 15, "translation"),
    _record(3, "0x0000000000000000000000000000000000000013", 5, "code_generation"),
    _record(4, "0x0000000000000000000000000000000000000014", 85, "translation"),
)


@dataclass(frozen=True, slots=True)
class ControlledVerifier:
    """Stand in for the chain verifier so aggregation is quick to repeat."""

    def verify(
        self,
        record: FeedbackRecord,
        agent: RegisteredAgent,
    ) -> VerifiedInteraction:
        del agent
        if record.block_number == 2:
            raise EvidenceVerificationError("evidence URI is not a local file URI")
        payment = "0x" + ("ab" * 32 if record.block_number in {1, 4} else "cd" * 32)
        return VerifiedInteraction(payment_transaction=payment, amount_atomic=25_000)


def main() -> None:
    views = evaluate_reputation_records(
        RECORDS,
        (AGENT,),
        "translation",
        ControlledVerifier(),
    )[AGENT.identity.agent_id]

    assert views.raw.average == Decimal("47.5") and views.raw.count == 4
    assert views.task_typed.average == Decimal(185) / Decimal(3)
    assert views.task_typed.count == 3
    assert views.interaction_verified.average == Decimal(85)
    assert views.interaction_verified.count == 1
    assert {item.reason for item in views.verification_rejections} == {
        "evidence URI is not a local file URI",
        "payment receipt was already used by earlier feedback",
    }

    print("Controlled reputation scenario: PASS")
    print("Raw:                  47.50 (4 records)")
    print("Task-typed:           61.67 (3 records)")
    print("Interaction-verified: 85.00 (1 record)")
    print("Excluded: missing evidence and reused payment receipt")


if __name__ == "__main__":
    main()
