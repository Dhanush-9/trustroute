"""Validate, register, and publish one configured A2A agent in ERC-8004."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx
from a2a.client import A2ACardResolver
from a2a.client.errors import A2AClientError
from eth_account import Account

from agent.cards import read_listing, read_skill_listing
from agent.config import AgentConfig
from erc8004.identity import IdentityRegistryClient, LocalDeployment
from erc8004.registration import REGISTRATION_TYPE
from x402_support.network import PaymentNetwork


async def _validate_agent_card(
    config: AgentConfig,
    network: PaymentNetwork | None,
) -> None:
    """Fail before registration if the configured service is not really live."""

    async with httpx.AsyncClient(timeout=15, trust_env=False) as http:
        resolver = A2ACardResolver(httpx_client=http, base_url=config.base_url)
        card = await resolver.get_agent_card()

    if card.name != config.name:
        raise ValueError(
            f"AgentCard name {card.name!r} does not match config {config.name!r}"
        )
    configured_skills = set(config.skill_ids)
    advertised_skills = {skill.id for skill in card.skills}
    if advertised_skills != configured_skills:
        raise ValueError(
            "AgentCard skills do not match configured skills: "
            f"expected {sorted(configured_skills)}, got {sorted(advertised_skills)}"
        )
    if not any(
        interface.url.rstrip("/") == config.base_url
        for interface in card.supported_interfaces
    ):
        raise ValueError("AgentCard interface does not match configured baseUrl")

    if config.payment is not None and network is not None:
        listing = read_listing(card)
        if listing is None:
            raise ValueError("paid AgentCard does not contain marketplace metadata")
        for skill in config.skills:
            skill_listing = read_skill_listing(card, skill.skill_id)
            if skill_listing is None:
                raise ValueError(
                    f"AgentCard has no price for skill {skill.skill_id!r}"
                )
            expected_atomic = skill.price_atomic or ""
            expected_display = network.display_amount(expected_atomic)
            if (
                skill_listing.get("amount_atomic") != expected_atomic
                or skill_listing.get("amount") != expected_display
                or skill_listing.get("asset_symbol") != network.asset_symbol
                or str(skill_listing.get("asset_address", "")).lower()
                != network.asset.lower()
                or skill_listing.get("network") != network.network
            ):
                raise ValueError(
                    f"AgentCard price for {skill.skill_id!r} does not match config"
                )


def _registration_document(config: AgentConfig, identity) -> dict:
    return {
        "type": REGISTRATION_TYPE,
        "name": config.name,
        "description": config.description,
        "image": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E",
        "services": [
            {
                "name": "A2A",
                "endpoint": config.agent_card_url,
                "version": "1.0",
            }
        ],
        "x402Support": config.payment is not None,
        "active": True,
        "registrations": [
            {
                "agentId": identity.agent_id,
                "agentRegistry": identity.registry,
            }
        ],
        "supportedTrust": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="configuration of the running agent to register",
    )
    parser.add_argument(
        "--deployment",
        type=Path,
        default=Path("var/identity-deployment.json"),
        help="Identity Registry deployment record",
    )
    args = parser.parse_args()

    try:
        config = AgentConfig.from_path(args.config)
        if config.registration is None:
            raise ValueError("agent configuration does not enable registration")

        owner_key_env = config.registration.owner_key_env
        private_key = os.environ.get(owner_key_env)
        if not private_key:
            raise RuntimeError(f"{owner_key_env} is required")
        owner = Account.from_key(private_key)

        identity_deployment = LocalDeployment.from_path(args.deployment)
        if identity_deployment.chain_id != 31337:
            raise RuntimeError("this checkpoint command is restricted to a local chain")

        payment_network = None
        if config.payment is not None:
            payment_network = PaymentNetwork.from_path(
                config.payment.network_deployment
            )
            if payment_network.chain_id != identity_deployment.chain_id:
                raise RuntimeError("ERC-8004 and x402 use different chains")
            if owner.address.lower() != config.payment.recipient.lower():
                raise ValueError(
                    "payment recipient must equal the registering owner"
                )

        asyncio.run(_validate_agent_card(config, payment_network))

        registry = IdentityRegistryClient(
            identity_deployment,
            private_key=private_key,
        )
        identity, register_tx = registry.register()

        registered_owner = registry.owner_of(identity.agent_id)
        agent_wallet = registry.agent_wallet(identity.agent_id)
        if registered_owner.lower() != owner.address.lower():
            raise RuntimeError("registered owner does not match signing wallet")
        if config.payment is not None:
            if agent_wallet.lower() != config.payment.recipient.lower():
                raise RuntimeError(
                    "ERC-8004 agentWallet does not match x402 payment recipient"
                )

        document = _registration_document(config, identity)
        output = config.registration.document_path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

        uri_tx = registry.set_agent_uri(
            identity.agent_id,
            config.registration.public_url,
        )

        # The running agent reads the exact file above for this HTTP endpoint.
        with httpx.Client(timeout=15, trust_env=False) as http:
            response = http.get(config.registration.public_url)
            response.raise_for_status()
            if response.json() != document:
                raise RuntimeError("served registration document differs from output file")

        print(f"Agent: {config.name}")
        print(f"Skills: {list(config.skill_ids)}")
        print(f"Identity: {identity}")
        print(f"Owner: {registered_owner}")
        print(f"Agent wallet: {agent_wallet}")
        print("Payment recipient binding: verified")
        print(f"agentURI: {registry.token_uri(identity.agent_id)}")
        print(f"Registration file: {output}")
        print(f"Register tx: {register_tx}")
        print(f"URI tx: {uri_tx}")
    except (
        A2AClientError,
        ConnectionError,
        FileNotFoundError,
        KeyError,
        RuntimeError,
        ValueError,
        httpx.HTTPError,
    ) as error:
        parser.exit(1, f"Registration failed: {error}\n")


if __name__ == "__main__":
    main()
