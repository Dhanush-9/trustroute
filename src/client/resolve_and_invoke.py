"""Resolve one known ERC-8004 agent, pay it, and invoke it through A2A."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import httpx
from a2a.client.errors import A2AClientError
from web3.exceptions import Web3Exception
from x402.http.clients.httpx import PaymentError

from client.config import ClientPaymentPolicy
from client.demo_client import invoke
from client.output import heading
from client.payment import (
    PaymentPolicyError,
    build_paying_transport,
    validate_advertised_price,
)
from erc8004.identity import LocalDeployment
from erc8004.registration import RegistrationError
from marketplace.catalog import CatalogEntry, CatalogError, resolve_agent
from x402_support.network import PaymentNetwork


@dataclass(frozen=True, slots=True)
class InvocationPlan:
    entry: CatalogEntry
    policy: ClientPaymentPolicy
    network: PaymentNetwork


def prepare_entry(
    entry: CatalogEntry,
    identity_deployment: LocalDeployment,
    client_policy_path: Path,
) -> InvocationPlan:
    """Validate identity, listing, network, asset, and budget before task input."""

    policy = ClientPaymentPolicy.from_path(client_policy_path)
    network = PaymentNetwork.from_path(policy.network_deployment)
    if network.chain_id != identity_deployment.chain_id:
        raise CatalogError("ERC-8004 and client payment policy use different chains")

    heading("SELECTED IDENTITY")
    print(f"Registry: {entry.agent.identity.registry}")
    print(f"Agent ID: {entry.agent.identity.agent_id}")
    print(f"Agent: {entry.card.name}")
    print(f"Owner: {entry.agent.owner}")
    print(f"ERC-8004 agentWallet: {entry.agent.agent_wallet}")
    print(f"agentURI: {entry.agent.agent_uri}")
    print("Registration identity: verified")
    print(f"Requested skill: {entry.skill_id}")

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

    return InvocationPlan(entry=entry, policy=policy, network=network)


async def prepare_invocation(
    identity_deployment_path: Path,
    client_policy_path: Path,
    agent_id: int,
    skill_id: str,
) -> InvocationPlan:
    """Resolve and validate a known candidate without requesting task input."""

    identity_deployment = LocalDeployment.from_path(identity_deployment_path)
    entry = await resolve_agent(identity_deployment_path, agent_id, skill_id)
    return prepare_entry(entry, identity_deployment, client_policy_path)


async def invoke_plan(plan: InvocationPlan, source: str) -> None:
    """Pay and invoke a previously validated candidate."""

    entry = plan.entry
    transport = build_paying_transport(
        plan.network,
        plan.policy,
        expected_recipient=entry.agent.agent_wallet,
        expected_amount_atomic=entry.price.amount_atomic,
    )
    await invoke(
        entry.base_url,
        source,
        skill_id=entry.skill_id,
        transport=transport,
        expected_amount_atomic=entry.price.amount_atomic,
    )


async def resolve_and_invoke(
    identity_deployment_path: Path,
    client_policy_path: Path,
    agent_id: int,
    skill_id: str,
    source: str,
) -> None:
    """Compatibility entry point for scripted direct invocation."""

    plan = await prepare_invocation(
        identity_deployment_path,
        client_policy_path,
        agent_id,
        skill_id,
    )
    await invoke_plan(plan, source)


def read_multiline_input() -> str:
    print("\nPaste the task input. Press Enter twice when done.\n")
    lines: list[str] = []
    while True:
        line = input()
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines)


async def _run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    plan = await prepare_invocation(
        args.deployment,
        args.policy,
        args.agent_id,
        args.skill,
    )
    source = args.message if args.message is not None else read_multiline_input()
    if not source.strip():
        parser.error("message must not be empty")
    await invoke_plan(plan, source)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--deployment",
        type=Path,
        default=Path("var/identity-deployment.json"),
        help="local Identity Registry deployment record",
    )
    parser.add_argument("--agent-id", required=True, type=int)
    parser.add_argument(
        "--skill",
        required=True,
        help="exact AgentCard skill ID to invoke",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("configs/client/local-client.json"),
        help="client-owned wallet and maximum-payment policy",
    )
    parser.add_argument(
        "--message",
        help="task input; when omitted, multiline input is read interactively",
    )
    args = parser.parse_args()

    if args.agent_id < 0:
        parser.error("agent ID must not be negative")

    try:
        asyncio.run(_run(args, parser))
    except PaymentPolicyError as error:
        parser.exit(1, f"Payment policy rejected the agent: {error}\n")
    except PaymentError as error:
        parser.exit(1, f"x402 payment failed: {error}\n")
    except (
        A2AClientError,
        CatalogError,
        ConnectionError,
        FileNotFoundError,
        KeyError,
        RegistrationError,
        RuntimeError,
        ValueError,
        Web3Exception,
        httpx.HTTPError,
        json.JSONDecodeError,
    ) as error:
        parser.exit(1, f"Resolution or invocation failed: {error}\n")


if __name__ == "__main__":
    main()
