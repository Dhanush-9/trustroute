"""Resolve and invoke one explicitly located A2A agent."""

import argparse
import asyncio
import time
from dataclasses import dataclass

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.client.errors import A2AClientError
from a2a.helpers import get_message_text, new_text_message
from a2a.types import SendMessageRequest

from agent.cards import read_listing, read_skill_listing
from agent.skill_routing import (
    SKILL_HEADER,
    SKILL_METADATA_KEY,
    SKILL_ROUTING_EXTENSION_URI,
)
from client.output import heading


@dataclass(frozen=True, slots=True)
class A2AResult:
    """Correlation identifiers and content returned by one A2A invocation."""

    agent_card_url: str
    interface_url: str
    context_id: str
    task_id: str
    response: str
    latency_ms: int


def _agent_card_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/.well-known/agent-card.json"


async def invoke(
    base_url: str,
    source: str,
    *,
    skill_id: str,
    transport: httpx.AsyncBaseTransport | None = None,
    expected_amount_atomic: str | None = None,
) -> A2AResult:
    """Resolve an AgentCard and invoke one explicitly selected skill."""

    # Local requests should not be redirected through a system HTTP proxy.
    async with httpx.AsyncClient(
        timeout=120,
        trust_env=False,
        transport=transport,
        headers={SKILL_HEADER: skill_id},
    ) as http:
        resolver = A2ACardResolver(
            httpx_client=http,
            base_url=base_url.rstrip("/"),
        )
        card = await resolver.get_agent_card()

        if not card.supported_interfaces:
            raise A2AClientError("AgentCard does not advertise an interface")

        interface = card.supported_interfaces[0]
        skill_ids = [skill.id for skill in card.skills]
        if skill_id not in skill_ids:
            raise A2AClientError(
                f"agent does not advertise requested skill {skill_id!r}"
            )
        listing = read_listing(card)
        skill_listing = read_skill_listing(card, skill_id)

        if expected_amount_atomic is not None:
            current_amount = (
                skill_listing.get("amount_atomic")
                if skill_listing is not None
                else None
            )
            if current_amount != expected_amount_atomic:
                raise A2AClientError(
                    "AgentCard skill price changed after candidate selection"
                )

        heading("A2A AGENTCARD")
        print(f"AgentCard: {_agent_card_url(base_url)}")
        print(f"Agent: {card.name}")
        print(f"Version: {card.version}")
        print(f"Protocol: {interface.protocol_binding} {interface.protocol_version}")
        print(f"Interface: {interface.url}")
        print(f"Skills: {skill_ids}")
        print(f"Requested skill: {skill_id}")
        print("Skill advertised by AgentCard: verified")

        if listing is None or skill_listing is None:
            print("Advertised price: not provided")
        else:
            print(
                "Advertised skill price: "
                f"{skill_listing.get('amount')} "
                f"{skill_listing.get('asset_symbol')}"
            )
            print(f"Listing authority: {listing.get('listing_authority')}")
            print(f"Price authority: {listing.get('authoritative_quote')}")

        client = await create_client(card, ClientConfig(httpx_client=http))
        try:
            message = new_text_message(source)
            message.extensions.append(SKILL_ROUTING_EXTENSION_URI)
            request = SendMessageRequest(
                message=message,
                metadata={SKILL_METADATA_KEY: skill_id},
            )
            result: A2AResult | None = None
            start_time = time.perf_counter()

            async for chunk in client.send_message(request):
                if chunk.HasField("message"):
                    round_trip_ms = round(
                        (time.perf_counter() - start_time) * 1000
                    )
                    response_text = get_message_text(chunk.message)
                    result = A2AResult(
                        agent_card_url=_agent_card_url(base_url),
                        interface_url=interface.url,
                        context_id=chunk.message.context_id,
                        task_id=chunk.message.task_id,
                        response=response_text,
                        latency_ms=round_trip_ms,
                    )
                    heading("A2A RESULT")
                    print(f"Context ID: {chunk.message.context_id}")
                    print(f"Task ID: {chunk.message.task_id}")
                    print(f"Client-observed invocation: {round_trip_ms} ms")
                    print(f"Response: {response_text}")

        finally:
            # The A2A client may own transport resources in addition to HTTP.
            await client.close()

        if result is None:
            raise A2AClientError("agent returned no A2A message")
        return result


def _read_multiline_input() -> str:
    print("Paste the task input. Press Enter twice when done.\n")
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
        "--url",
        required=True,
        help="Known base URL of the A2A agent, for example http://localhost:8001",
    )
    parser.add_argument(
        "--skill",
        required=True,
        help="exact AgentCard skill ID to invoke",
    )
    parser.add_argument(
        "--message",
        help="task input; when omitted, multiline input is read interactively",
    )
    args = parser.parse_args()

    source = args.message if args.message is not None else _read_multiline_input()
    if not source.strip():
        parser.error("message must not be empty")

    try:
        asyncio.run(invoke(args.url, source, skill_id=args.skill))
    except (A2AClientError, httpx.HTTPError) as error:
        parser.exit(1, f"A2A invocation at {args.url} failed: {error}\n")


if __name__ == "__main__":
    main()
