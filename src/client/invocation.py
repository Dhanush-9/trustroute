"""Validate, pay for, and invoke one already selected agent skill."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from client.config import ClientPaymentPolicy
from client.demo_client import A2AResult, invoke
from client.output import heading
from client.payment import (
    PaymentPolicyError,
    PaymentReceipt,
    build_paying_transport,
    validate_advertised_price,
)
from erc8004.identity import LocalDeployment
from marketplace.catalog import CatalogEntry, CatalogError
from x402_support.network import PaymentNetwork


@dataclass(frozen=True, slots=True)
class InvocationPlan:
    """Everything validated before the client sends the paid request."""

    entry: CatalogEntry
    task_type: str
    policy: ClientPaymentPolicy
    network: PaymentNetwork


@dataclass(frozen=True, slots=True)
class PaidInvocation:
    """The A2A result and x402 receipt produced by one interaction."""

    a2a: A2AResult
    payment: PaymentReceipt


def prepare_entry(
    entry: CatalogEntry,
    task_type: str,
    identity_deployment: LocalDeployment,
    client_policy_path: Path,
) -> InvocationPlan:
    """Validate identity, price, network, asset, and budget before payment."""

    policy = ClientPaymentPolicy.from_path(client_policy_path)
    network = PaymentNetwork.from_path(policy.network_deployment)
    if network.chain_id != identity_deployment.chain_id:
        raise CatalogError("ERC-8004 and client payment policy use different chains")

    heading("SELECTED AGENT AND SKILL")
    print(f"Registry: {entry.agent.identity.registry}")
    print(f"Agent ID: {entry.agent.identity.agent_id}")
    print(f"Agent: {entry.card.name}")
    print(f"Owner: {entry.agent.owner}")
    print(f"ERC-8004 agentWallet: {entry.agent.agent_wallet}")
    print(f"agentURI: {entry.agent.agent_uri}")
    print("Registration identity: verified")
    print(f"Task type: {task_type}")
    print(f"Agent-local skill ID: {entry.skill_id}")

    heading("PAYMENT POLICY")
    print(
        f"Advertised skill price: {entry.price.amount} "
        f"{entry.price.asset_symbol} ({entry.price.amount_atomic} atomic units)"
    )
    print(
        f"Client maximum: {network.display_amount(policy.max_amount_atomic)} "
        f"{network.asset_symbol}"
    )
    try:
        validate_advertised_price(
            network,
            policy,
            amount_atomic=entry.price.amount_atomic,
            advertised_network=entry.price.network,
            advertised_asset=entry.price.asset_address,
        )
    except PaymentPolicyError:
        print("Budget decision: rejected")
        raise
    print("Advertised network and asset: verified")
    print("Budget decision: accepted")

    return InvocationPlan(
        entry=entry,
        task_type=task_type,
        policy=policy,
        network=network,
    )


async def invoke_plan(plan: InvocationPlan, source: str) -> PaidInvocation:
    """Pay and invoke a candidate that has already passed client checks."""

    entry = plan.entry
    payment_session = build_paying_transport(
        plan.network,
        plan.policy,
        expected_recipient=entry.agent.agent_wallet,
        expected_amount_atomic=entry.price.amount_atomic,
    )
    a2a_result = await invoke(
        entry.base_url,
        source,
        skill_id=entry.skill_id,
        transport=payment_session.transport,
        expected_amount_atomic=entry.price.amount_atomic,
    )
    return PaidInvocation(
        a2a=a2a_result,
        payment=payment_session.require_receipt(),
    )
