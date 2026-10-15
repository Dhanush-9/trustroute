"""Build a live skill catalog from ERC-8004 identities and A2A AgentCards."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from a2a.client import A2ACardResolver
from a2a.client.errors import A2AClientError
from a2a.types import AgentCard
from google.protobuf.json_format import MessageToDict
from web3.exceptions import Web3Exception

from agent.cards import read_skill_listing
from agent.skill_routing import (
    SKILL_HEADER,
    SKILL_METADATA_KEY,
    SKILL_ROUTING_EXTENSION_URI,
)
from erc8004.identity import IdentityRegistryClient, LocalDeployment, RegisteredAgent
from erc8004.registration import (
    RegistrationDocument,
    RegistrationError,
    parse_registration_document,
)


AGENT_CARD_PATH = "/.well-known/agent-card.json"


class CatalogError(RuntimeError):
    """A registered identity could not become a safe marketplace entry."""


@dataclass(frozen=True, slots=True)
class SkillPrice:
    amount: str
    amount_atomic: str
    asset_symbol: str
    asset_address: str
    network: str


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    agent: RegisteredAgent
    registration: RegistrationDocument
    card: AgentCard
    base_url: str
    skill_id: str
    price: SkillPrice


@dataclass(frozen=True, slots=True)
class SkippedAgent:
    agent_id: int
    reason: str


@dataclass(frozen=True, slots=True)
class Catalog:
    entries: tuple[CatalogEntry, ...]
    skipped: tuple[SkippedAgent, ...]


def base_url_from_agent_card(endpoint: str) -> str:
    """Convert an AgentCard endpoint into the service base URL."""

    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
        or not parsed.path.endswith(AGENT_CARD_PATH)
    ):
        raise CatalogError(
            f"A2A endpoint must be an HTTP URL ending with {AGENT_CARD_PATH}"
        )
    base_path = parsed.path.removesuffix(AGENT_CARD_PATH)
    return urlunsplit((parsed.scheme, parsed.netloc, base_path, "", "")).rstrip("/")


def _required_listing_string(listing: dict, field: str) -> str:
    value = listing.get(field)
    if not isinstance(value, str) or not value:
        raise CatalogError(f"skill listing is missing {field!r}")
    return value


def _skill_price(card: AgentCard, skill_id: str) -> SkillPrice:
    listing = read_skill_listing(card, skill_id)
    if listing is None:
        raise CatalogError(f"AgentCard has no price for skill {skill_id!r}")

    amount_atomic = _required_listing_string(listing, "amount_atomic")
    if not amount_atomic.isdigit() or int(amount_atomic) <= 0:
        raise CatalogError("skill listing amount_atomic must be a positive integer")

    return SkillPrice(
        amount=_required_listing_string(listing, "amount"),
        amount_atomic=amount_atomic,
        asset_symbol=_required_listing_string(listing, "asset_symbol"),
        asset_address=_required_listing_string(listing, "asset_address"),
        network=_required_listing_string(listing, "network"),
    )


def _validate_skill_routing(card: AgentCard) -> None:
    extension = next(
        (
            item
            for item in card.capabilities.extensions or []
            if item.uri == SKILL_ROUTING_EXTENSION_URI
        ),
        None,
    )
    if extension is None or not extension.required:
        raise CatalogError("AgentCard does not require TrustRoute skill binding")

    params = MessageToDict(extension.params)
    if (
        params.get("http_header") != SKILL_HEADER
        or params.get("request_metadata_key") != SKILL_METADATA_KEY
    ):
        raise CatalogError("AgentCard advertises an incompatible skill binding")


async def resolve_registered_agent(
    registry: IdentityRegistryClient,
    agent_id: int,
    skill_id: str,
    http: httpx.AsyncClient,
) -> CatalogEntry:
    """Resolve and validate one registered agent for a requested skill."""

    try:
        agent = registry.read_agent(agent_id)
    except Web3Exception as error:
        raise CatalogError(f"agent ID {agent_id} does not exist") from error

    if not agent.agent_uri:
        raise CatalogError("empty agentURI")
    if int(agent.agent_wallet, 16) == 0:
        raise CatalogError("agentWallet is unset")

    uri = urlsplit(agent.agent_uri)
    if uri.scheme not in {"http", "https"} or not uri.netloc:
        raise CatalogError("agentURI is not an HTTP URL")

    response = await http.get(agent.agent_uri)
    response.raise_for_status()
    try:
        registration_data = response.json()
    except json.JSONDecodeError as error:
        raise CatalogError("agentURI did not return valid JSON") from error

    registration = parse_registration_document(
        registration_data,
        expected_identity=agent.identity,
    )
    if not registration.x402_support:
        raise CatalogError("registration does not advertise x402 support")

    service = registration.a2a_service
    base_url = base_url_from_agent_card(service.endpoint)
    resolver = A2ACardResolver(httpx_client=http, base_url=base_url)
    card = await resolver.get_agent_card()

    if card.name != registration.name:
        raise CatalogError("registration name and AgentCard name differ")
    _validate_skill_routing(card)
    if skill_id not in {skill.id for skill in card.skills}:
        raise CatalogError(f"skill {skill_id!r} is not advertised")
    if not any(
        interface.url.rstrip("/") == base_url
        for interface in card.supported_interfaces
    ):
        raise CatalogError("AgentCard interface differs from registration service")

    return CatalogEntry(
        agent=agent,
        registration=registration,
        card=card,
        base_url=base_url,
        skill_id=skill_id,
        price=_skill_price(card, skill_id),
    )


async def discover_agents(
    deployment_path: Path,
    skill_id: str,
) -> Catalog:
    """Return all live registered agents that safely advertise one skill."""

    deployment = LocalDeployment.from_path(deployment_path)
    registry = IdentityRegistryClient(deployment)
    entries: list[CatalogEntry] = []
    skipped: list[SkippedAgent] = []

    async with httpx.AsyncClient(timeout=15, trust_env=False) as http:
        for agent_id in registry.registered_agent_ids():
            try:
                entry = await resolve_registered_agent(
                    registry,
                    agent_id,
                    skill_id,
                    http,
                )
            except (
                A2AClientError,
                CatalogError,
                RegistrationError,
                Web3Exception,
                httpx.HTTPError,
            ) as error:
                skipped.append(SkippedAgent(agent_id, str(error)))
            else:
                entries.append(entry)

    return Catalog(tuple(entries), tuple(skipped))


async def resolve_agent(
    deployment_path: Path,
    agent_id: int,
    skill_id: str,
) -> CatalogEntry:
    """Resolve one explicitly known ID through the same catalog validation."""

    deployment = LocalDeployment.from_path(deployment_path)
    registry = IdentityRegistryClient(deployment)
    async with httpx.AsyncClient(timeout=15, trust_env=False) as http:
        return await resolve_registered_agent(registry, agent_id, skill_id, http)
