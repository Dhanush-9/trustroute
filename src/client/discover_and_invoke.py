"""Discover ERC-8004 agents by skill, choose one, pay, and invoke it."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx
from a2a.client.errors import A2AClientError
from web3.exceptions import Web3Exception
from x402.http.clients.httpx import PaymentError

from client.config import ClientPaymentPolicy
from client.output import heading
from client.payment import PaymentPolicyError, validate_advertised_price
from client.resolve_and_invoke import (
    invoke_plan,
    prepare_entry,
    read_multiline_input,
)
from erc8004.identity import LocalDeployment
from erc8004.registration import RegistrationError
from marketplace.catalog import Catalog, CatalogEntry, CatalogError, discover_agents
from x402_support.network import PaymentNetwork


def _within_budget(
    entry: CatalogEntry,
    network: PaymentNetwork,
    policy: ClientPaymentPolicy,
) -> bool:
    try:
        validate_advertised_price(
            network,
            policy,
            amount_atomic=entry.price.amount_atomic,
            advertised_network=entry.price.network,
            advertised_asset=entry.price.asset_address,
        )
    except PaymentPolicyError:
        return False
    return True


def _print_catalog(
    catalog: Catalog,
    skill_id: str,
    network: PaymentNetwork,
    policy: ClientPaymentPolicy,
) -> None:
    heading("ERC-8004 SKILL DISCOVERY")
    print(f"Requested skill: {skill_id}")
    print(f"Registered identities scanned: {len(catalog.entries) + len(catalog.skipped)}")
    print()

    if catalog.entries:
        print(f"{'ID':<5} {'AGENT':<24} {'PRICE':<18} {'IN BUDGET'}")
        print("-" * 68)
        for entry in catalog.entries:
            price = f"{entry.price.amount} {entry.price.asset_symbol}"
            budget = "yes" if _within_budget(entry, network, policy) else "no"
            print(
                f"{entry.agent.identity.agent_id:<5} "
                f"{entry.card.name:<24} "
                f"{price:<18} "
                f"{budget}"
            )
    else:
        print("No eligible agents advertise this skill.")

    if catalog.skipped:
        print("\nSkipped registrations:")
        for skipped in catalog.skipped:
            print(f"  {skipped.agent_id}: {skipped.reason}")


def _choose_entry(
    entries: tuple[CatalogEntry, ...],
    requested_agent_id: int | None,
) -> CatalogEntry:
    by_id = {entry.agent.identity.agent_id: entry for entry in entries}
    if requested_agent_id is not None:
        if requested_agent_id not in by_id:
            raise CatalogError(
                f"agent ID {requested_agent_id} is not eligible for the requested skill"
            )
        return by_id[requested_agent_id]

    while True:
        try:
            raw_value = input("\nSelect an eligible agent ID: ").strip()
        except EOFError as error:
            raise CatalogError("no agent ID was selected") from error
        try:
            agent_id = int(raw_value)
        except ValueError:
            print("Please enter a numeric agent ID.")
            continue
        if agent_id in by_id:
            return by_id[agent_id]
        print(f"Choose one of: {sorted(by_id)}")


async def _run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    identity_deployment = LocalDeployment.from_path(args.deployment)
    policy = ClientPaymentPolicy.from_path(args.policy)
    network = PaymentNetwork.from_path(policy.network_deployment)
    if network.chain_id != identity_deployment.chain_id:
        raise CatalogError("ERC-8004 and client payment policy use different chains")

    catalog = await discover_agents(args.deployment, args.skill)
    _print_catalog(catalog, args.skill, network, policy)
    if not catalog.entries:
        raise CatalogError(f"no eligible agents found for skill {args.skill!r}")

    entry = _choose_entry(catalog.entries, args.agent_id)
    plan = prepare_entry(entry, identity_deployment, args.policy)

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
    parser.add_argument(
        "--skill",
        required=True,
        help="exact AgentCard skill ID to discover",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("configs/client/local-client.json"),
        help="client-owned wallet and maximum-payment policy",
    )
    parser.add_argument(
        "--agent-id",
        type=int,
        help="choose an eligible ID non-interactively; otherwise prompt",
    )
    parser.add_argument(
        "--message",
        help="task input; when omitted, prompt after agent selection",
    )
    args = parser.parse_args()

    if args.agent_id is not None and args.agent_id < 0:
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
        parser.exit(1, f"Discovery or invocation failed: {error}\n")


if __name__ == "__main__":
    main()
