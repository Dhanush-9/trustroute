"""Explainable reputation-aware selection among eligible agent skills."""

from __future__ import annotations

import math
from dataclasses import dataclass

from client.config import ClientPaymentPolicy
from client.intent import SkillMatch
from client.payment import PaymentPolicyError, validate_advertised_price
from marketplace.catalog import CatalogError
from reputation.views import AgentReputation
from x402_support.network import PaymentNetwork


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    """One affordable candidate and every value used to rank it."""

    match: SkillMatch
    reputation: AgentReputation
    reputation_estimate: float
    price_score: float
    cold_start_bonus: float
    total_score: float

    @property
    def agent_id(self) -> int:
        return self.match.entry.agent.identity.agent_id


def _reputation_estimate(
    reputation: AgentReputation,
    policy: ClientPaymentPolicy,
) -> float:
    """Shrink sparse verified ratings toward a neutral client-owned prior."""

    score = reputation.interaction_verified
    observed_total = (
        float(score.average) * score.count if score.average is not None else 0.0
    )
    prior = policy.selection
    return (
        observed_total + prior.prior_score * prior.prior_weight
    ) / (score.count + prior.prior_weight)


def rank_candidates(
    matches: tuple[SkillMatch, ...],
    reputation: dict[int, AgentReputation],
    network: PaymentNetwork,
    policy: ClientPaymentPolicy,
) -> tuple[RankedCandidate, ...]:
    """Rank affordable candidates using verified trust, meaning, and price."""

    ranked: list[RankedCandidate] = []
    maximum = int(policy.max_amount_atomic)
    for match in matches:
        entry = match.entry
        try:
            validate_advertised_price(
                network,
                policy,
                amount_atomic=entry.price.amount_atomic,
                advertised_network=entry.price.network,
                advertised_asset=entry.price.asset_address,
            )
        except PaymentPolicyError:
            continue

        views = reputation[entry.agent.identity.agent_id]
        verified_count = views.interaction_verified.count
        trust = _reputation_estimate(views, policy)
        price_score = 1 - (int(entry.price.amount_atomic) / maximum)
        cold_start_bonus = policy.selection.cold_start_bonus / math.sqrt(
            verified_count + 1
        )
        total = (
            policy.selection.reputation_weight * (trust / 100)
            + policy.selection.semantic_weight * match.similarity
            + policy.selection.price_weight * price_score
            + cold_start_bonus
        )
        ranked.append(
            RankedCandidate(
                match=match,
                reputation=views,
                reputation_estimate=trust,
                price_score=price_score,
                cold_start_bonus=cold_start_bonus,
                total_score=total,
            )
        )

    return tuple(
        sorted(
            ranked,
            key=lambda item: (
                -item.total_score,
                -item.reputation.interaction_verified.count,
                -item.match.similarity,
                int(item.match.entry.price.amount_atomic),
                item.agent_id,
            ),
        )
    )


def select_candidate(
    ranked: tuple[RankedCandidate, ...],
    requested_agent_id: int | None,
) -> RankedCandidate:
    """Choose the ranking winner, unless an eligible experiment override exists."""

    if not ranked:
        raise PaymentPolicyError("no semantically matching agent is within budget")
    if requested_agent_id is None:
        return ranked[0]

    for candidate in ranked:
        if candidate.agent_id == requested_agent_id:
            return candidate
    eligible = [candidate.agent_id for candidate in ranked]
    raise CatalogError(
        f"agent ID {requested_agent_id} is not an affordable eligible candidate; "
        f"choose one of {eligible}"
    )
