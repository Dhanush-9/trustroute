"""Resolve one known ERC-8004 identity, pay it, and invoke it through A2A."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from a2a.client.errors import A2AClientError
from web3.exceptions import Web3Exception
from x402.http.clients.httpx import PaymentError

from client.config import ClientPaymentPolicy
from client.demo_client import invoke
from client.payment import build_paying_transport
from erc8004.identity import IdentityRegistryClient, LocalDeployment
from erc8004.registration import RegistrationError, parse_registration_document
from x402_support.network import PaymentNetwork


AGENT_CARD_PATH = "/.well-known/agent-card.json"


class ResolutionError(RuntimeError):
    """A known identity could not produce a safe, usable A2A endpoint."""


def _base_url_from_agent_card(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if parsed.query or parsed.fragment or not parsed.path.endswith(AGENT_CARD_PATH):
        raise ResolutionError(
            f"A2A endpoint must end with {AGENT_CARD_PATH} and have no query"
        )
    base_path = parsed.path.removesuffix(AGENT_CARD_PATH)
    return urlunsplit((parsed.scheme, parsed.netloc, base_path, "", "")).rstrip("/")


async def resolve_and_invoke(
    identity_deployment_path: Path,
    client_policy_path: Path,
    agent_id: int,
    source: str,
) -> None:
    identity_deployment = LocalDeployment.from_path(identity_deployment_path)
    registry = IdentityRegistryClient(identity_deployment)

    try:
        agent = registry.read_agent(agent_id)
    except Web3Exception as error:
        raise ResolutionError(
            f"agent ID {agent_id} does not exist in {registry.contract.address}"
        ) from error

    if not agent.agent_uri:
        raise ResolutionError(f"agent ID {agent_id} has an empty agentURI")
    if int(agent.agent_wallet, 16) == 0:
        raise ResolutionError(f"agent ID {agent_id} has no verified agentWallet")

    uri = urlsplit(agent.agent_uri)
    if uri.scheme not in {"http", "https"} or not uri.netloc:
        raise ResolutionError("this checkpoint supports HTTP(S) agentURI values")

    async with httpx.AsyncClient(timeout=15, trust_env=False) as http:
        response = await http.get(agent.agent_uri)
        response.raise_for_status()
        try:
            registration_data = response.json()
        except json.JSONDecodeError as error:
            raise ResolutionError("agentURI did not return valid JSON") from error

    registration = parse_registration_document(
        registration_data,
        expected_identity=agent.identity,
    )
    service = registration.a2a_service

    print(f"Registry: {agent.identity.registry}")
    print(f"Agent ID: {agent.identity.agent_id}")
    print(f"Owner: {agent.owner}")
    print(f"ERC-8004 agentWallet: {agent.agent_wallet}")
    print(f"agentURI: {agent.agent_uri}")
    print("Registration identity: verified")
    print(f"Active agent: {registration.name}")
    print(f"x402 support: {registration.x402_support}")
    print(f"A2A service: {service.endpoint} (version {service.version})\n")

    if not registration.x402_support:
        raise ResolutionError("registration does not advertise x402 support")

    policy = ClientPaymentPolicy.from_path(client_policy_path)
    network = PaymentNetwork.from_path(policy.network_deployment)
    if network.chain_id != identity_deployment.chain_id:
        raise ResolutionError("ERC-8004 and client payment policy use different chains")

    transport = build_paying_transport(
        network,
        policy,
        expected_recipient=agent.agent_wallet,
    )
    await invoke(
        _base_url_from_agent_card(service.endpoint),
        source,
        transport=transport,
    )


def _read_multiline_input() -> str:
    print("Paste text to summarize. Press Enter twice when done.\n")
    lines: list[str] = []
    while True:
        line = input()
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines)


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
        "--policy",
        type=Path,
        default=Path("configs/client/local-client.json"),
        help="client-owned wallet and maximum-payment policy",
    )
    parser.add_argument(
        "--message",
        help="message to send; when omitted, multiline input is read interactively",
    )
    args = parser.parse_args()

    if args.agent_id < 0:
        parser.error("agent ID must not be negative")
    source = args.message if args.message is not None else _read_multiline_input()
    if not source.strip():
        parser.error("message must not be empty")

    try:
        asyncio.run(
            resolve_and_invoke(
                identity_deployment_path=args.deployment,
                client_policy_path=args.policy,
                agent_id=args.agent_id,
                source=source,
            )
        )
    except (
        A2AClientError,
        ConnectionError,
        FileNotFoundError,
        KeyError,
        PaymentError,
        RegistrationError,
        ResolutionError,
        RuntimeError,
        ValueError,
        Web3Exception,
        httpx.HTTPError,
        json.JSONDecodeError,
    ) as error:
        parser.exit(1, f"Resolution or invocation failed: {error}\n")


if __name__ == "__main__":
    main()
