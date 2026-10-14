"""Construction of A2A AgentCard"""

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentSkill,
)
from google.protobuf.struct_pb2 import Struct

from agent.config import SkillConfig
from agent.skill_routing import (
    SKILL_HEADER,
    SKILL_METADATA_KEY,
    SKILL_ROUTING_EXTENSION_URI,
)

# Identifier that tells clients how to interpret this custom extension.
MARKETPLACE_EXTENSION_URI = "https://trustroute.example/extensions/marketplace/v1"


def _dict_to_struct(data: dict) -> Struct:
    value = Struct()
    value.update(data)
    return value


def marketplace_extension(
    *,
    advertised_price: str,
    advertised_asset: str,
    authority: str,
) -> AgentExtension:
    """Return self-declared listing data, not an authoritative payment quote."""

    return AgentExtension(
        uri=MARKETPLACE_EXTENSION_URI,
        description="Marketplace discovery metadata",
        required=False,
        params=_dict_to_struct(
            {
                "advertised_price": advertised_price,
                "advertised_asset": advertised_asset,
                "listing_authority": authority,
                "authoritative_quote": "x402-payment-required",
            }
        ),
    )


def skill_routing_extension() -> AgentExtension:
    """Describe TrustRoute's explicit multi-skill dispatch convention."""

    return AgentExtension(
        uri=SKILL_ROUTING_EXTENSION_URI,
        description="Binds an A2A request to one advertised skill",
        required=False,
        params=_dict_to_struct(
            {
                "http_header": SKILL_HEADER,
                "request_metadata_key": SKILL_METADATA_KEY,
            }
        ),
    )


def build_agent_card(
    *,
    name: str,
    description: str,
    url: str,
    skills: tuple[SkillConfig, ...],
    listing: AgentExtension | None,
    version: str = "0.1.0",
) -> AgentCard:
    # The interface tells an A2A client where and how to send requests.
    interface = AgentInterface(
        protocol_binding="JSONRPC",
        url=url,
        protocol_version="1.0",
    )

    # Describe optional protocol behavior, such as streaming and extensions.
    extensions = [skill_routing_extension()]
    if listing is not None:
        extensions.append(listing)
    capabilities = AgentCapabilities(
        streaming=False,
        push_notifications=False,
        extensions=extensions,
    )

    advertised_skills = [
        AgentSkill(
            id=skill.skill_id,
            name=skill.name,
            description=skill.description,
            tags=list(skill.tags),
        )
        for skill in skills
    ]

    # The public card lets a client inspect the agent before invoking it.
    return AgentCard(
        name=name,
        description=description,
        version=version,
        supported_interfaces=[interface],
        capabilities=capabilities,
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=advertised_skills,
    )


def read_listing(card: AgentCard) -> dict | None:
    for extension in card.capabilities.extensions or []:
        if extension.uri == MARKETPLACE_EXTENSION_URI:
            return dict(extension.params)
    return None
