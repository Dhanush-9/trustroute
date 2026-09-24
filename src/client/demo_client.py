"""Resolve and invoke one explicitly located A2A agent."""

import argparse
import asyncio

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.client.errors import A2AClientError
from a2a.helpers import get_message_text, new_text_message
from a2a.types import SendMessageRequest

from agent.cards import read_listing


def _agent_card_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/.well-known/agent-card.json"


async def invoke(base_url: str, source: str) -> None:
    """Resolve the AgentCard, display it, and send one A2A message."""

    # Local requests should not be redirected through a system HTTP proxy.
    async with httpx.AsyncClient(timeout=120, trust_env=False) as http:
        resolver = A2ACardResolver(
            httpx_client=http,
            base_url=base_url.rstrip("/"),
        )
        card = await resolver.get_agent_card()

        if not card.supported_interfaces:
            raise A2AClientError("AgentCard does not advertise an interface")

        interface = card.supported_interfaces[0]
        skill_ids = [skill.id for skill in card.skills]
        listing = read_listing(card)

        print(f"AgentCard: {_agent_card_url(base_url)}")
        print(f"Agent: {card.name}")
        print(f"Version: {card.version}")
        print(f"Protocol: {interface.protocol_binding} {interface.protocol_version}")
        print(f"Interface: {interface.url}")
        print(f"Skills: {skill_ids}")

        if listing is None:
            print("Advertised price: not provided")
        else:
            print(f"Advertised price: {listing.get('advertised_price_usdc')} USDC")
            print(f"Price authority: {listing.get('authoritative_quote')}")

        client = await create_client(card, ClientConfig(httpx_client=http))
        try:
            request = SendMessageRequest(message=new_text_message(source))
            received_message = False

            async for chunk in client.send_message(request):
                if chunk.HasField("message"):
                    received_message = True
                    print(f"Context ID: {chunk.message.context_id}")
                    print(f"Task ID: {chunk.message.task_id}")
                    print(f"Response: {get_message_text(chunk.message)}")

        finally:
            # The A2A client may own transport resources in addition to HTTP.
            await client.close()

        if not received_message:
            raise A2AClientError("agent returned no A2A message")


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
        "--url",
        required=True,
        help="Known base URL of the A2A agent, for example http://localhost:8001",
    )
    parser.add_argument(
        "--message",
        help="Text to summarize; when omitted, multiline input is read interactively",
    )
    args = parser.parse_args()

    source = args.message if args.message is not None else _read_multiline_input()
    if not source.strip():
        parser.error("message must not be empty")

    try:
        asyncio.run(invoke(args.url, source))
    except (A2AClientError, httpx.HTTPError) as error:
        parser.exit(1, f"Could not reach A2A agent at {args.url}: {error}\n")


if __name__ == "__main__":
    main()
