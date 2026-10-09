"""Discover and invoke an A2A agent from its ERC-8004 identity."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from a2a.client.errors import A2AClientError
from web3.exceptions import Web3Exception

from client.demo_client import invoke
from erc8004.identity import IdentityRegistryClient, LocalDeployment
from erc8004.registration import RegistrationError, parse_registration_document


AGENT_CARD_PATH = "/.well-known/agent-card.json"


class DiscoveryError(RuntimeError):
    """Identity-rooted discovery could not produce a usable A2A endpoint."""


def _base_url_from_agent_card(endpoint: str) -> str:
    """Convert an advertised well-known AgentCard URL into its A2A base URL."""

    parsed = urlsplit(endpoint)
    if parsed.query or parsed.fragment or not parsed.path.endswith(AGENT_CARD_PATH):
        raise DiscoveryError(
            f"A2A endpoint must end with {AGENT_CARD_PATH} and have no query"
        )

    base_path = parsed.path.removesuffix(AGENT_CARD_PATH)
    return urlunsplit((parsed.scheme, parsed.netloc, base_path, "", "")).rstrip("/")


async def discover_and_invoke(
    deployment_path: Path,
    agent_id: int,
    source: str,
) -> None:
    """Resolve the identity, verify its document, then use the existing client."""

    deployment = LocalDeployment.from_path(deployment_path)
    registry = IdentityRegistryClient(deployment)

    try:
        agent = registry.read_agent(agent_id)
    except Web3Exception as error:
        raise DiscoveryError(
            f"agent ID {agent_id} does not exist in {registry.contract.address}"
        ) from error

    if not agent.agent_uri:
        raise DiscoveryError(f"agent ID {agent_id} has an empty agentURI")

    uri = urlsplit(agent.agent_uri)
    if uri.scheme not in {"http", "https"} or not uri.netloc:
        raise DiscoveryError("this checkpoint supports HTTP(S) agentURI values")

    async with httpx.AsyncClient(timeout=15, trust_env=False) as http:
        response = await http.get(agent.agent_uri)
        response.raise_for_status()
        try:
            registration_data = response.json()
        except json.JSONDecodeError as error:
            raise DiscoveryError("agentURI did not return valid JSON") from error

    registration = parse_registration_document(
        registration_data,
        expected_identity=agent.identity,
    )
    service = registration.a2a_service

    print(f"Registry: {agent.identity.registry}")
    print(f"Agent ID: {agent.identity.agent_id}")
    print(f"Owner: {agent.owner}")
    print(f"Agent wallet: {agent.agent_wallet}")
    print(f"agentURI: {agent.agent_uri}")
    print("Registration identity: verified")
    print(f"Active agent: {registration.name}")
    print(f"x402 support: {registration.x402_support}")
    print(f"A2A service: {service.endpoint} (version {service.version})")
    print()

    # From this point onward, Checkpoint 1's normal AgentCard/A2A path is reused.
    await invoke(_base_url_from_agent_card(service.endpoint), source)

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
    parser.add_argument(
        "--agent-id",
        required=True,
        type=int,
    )

    parser.add_argument(
        "--message",
        help="Message to send; when omitted, multiline input is read interactively"
    )
    args = parser.parse_args()

    if args.agent_id < 0:
        parser.error("agent ID must not be negative")

    source = (
        args.message
        if args.message is not None
        else _read_multiline_input()
    )

    if not source.strip():
        parser.error("message must not be empty")

    try:
        asyncio.run(
            discover_and_invoke(
                deployment_path=args.deployment,
                agent_id=args.agent_id,
                source=source,
            )
        )
    except (
        A2AClientError,
        ConnectionError,
        DiscoveryError,
        FileNotFoundError,
        KeyError,
        RegistrationError,
        RuntimeError,
        Web3Exception,
        httpx.HTTPError,
        json.JSONDecodeError,
    ) as error:
        parser.exit(1, f"Discovery failed: {error}\n")


if __name__ == "__main__":
    main()
