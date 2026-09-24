"""Invoke one explicitly selected A2A agent."""

import sys
import asyncio

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import get_message_text, new_text_message
from a2a.types import SendMessageRequest

from agent.cards import read_listing

URLS = {
    "fast": "http://localhost:8001",
    "accurate": "http://localhost:8002",
    "new": "http://localhost:8003",
    "ollama": "http://localhost:8004",
}


async def invoke(url: str, source: str) -> None:

    # Local development should not inherit corporate/system proxy settings.
    async with httpx.AsyncClient(timeout=120, trust_env=False) as http:
        card = await A2ACardResolver(httpx_client=http, base_url=url).get_agent_card()

        print(f"Agent: {card.name}")
        print(f"Skills: {[skill.id for skill in card.skills]}")
        print(f"Listing: {read_listing(card)}")

        client = await create_client(card, ClientConfig(httpx_client = http))
        try:
            request = SendMessageRequest(message=new_text_message(source))
            async for chunk in client.send_message(request):
                if chunk.HasField("message"):
                    print(f"Result: {get_message_text(chunk.message)}")

        finally:
            await client.close()


def _read_multiline_input() -> str:
    print("Paste text to summarize. Press Enter twice when done.\n")
    lines: list[str] = []

    while True:
        line = input()

        if line == "":
            break

        lines.append(line)
    
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise ValueError("Usage: python demo_client.py <profile>")
    
    profile = sys.argv[1]

    if profile not in URLS:
        raise ValueError(f"Unknown profile: {profile}\n")

    source = _read_multiline_input()

    asyncio.run(invoke(URLS[profile], source))
