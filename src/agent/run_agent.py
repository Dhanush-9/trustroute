import sys
import uvicorn

from cards import build_agent_card, marketplace_extension
from executor import DeterministicSummarizer, OllamaSummarizer
from server import build_app

PROFILES = {
    "fast": {
        "port": 8001, 
        "price": 0.01, 
        "latency_ms": 100, 
        "retention_ratio": 0.30
    },

    "accurate": {
        "port": 8002,
        "price": 0.05,
        "latency_ms": 2000,
        "retention_ratio": 0.80
    },

    "new": {
        "port": 8003,
        "price": 0.02,
        "latency_ms": 800, 
        "retention_ratio": 0.60
    },

    "ollama": {
        "port": 8004,
        "price": 0.03
    },
}


def main(profile: str) -> None:

    #retrieve configuration from PROFILES
    config = PROFILES[profile]
    
    url = f"http://localhost:{config['port']}/"
    name = f"summarizer-{profile}"

    card = build_agent_card(
        name=name,
        description=f"Text summarization agent ({profile} profile).",
        url=url,
        skill_id="summarize_text",
        skill_name="Summarize text",
        skill_description="Condenses a passage into a shorter summary.",
        tags=["summarization", "text"],
        listing=marketplace_extension(advertised_price_usdc=config["price"]),
    )

    if profile == "ollama":
        executor = OllamaSummarizer(agent_name = name)

    else:
        executor = DeterministicSummarizer(
            agent_name = name,
            latency_ms = config["latency_ms"],
            retention_ratio = config["retention_ratio"],
        )

    print(f"{name} -> {url}.well-known/agent-card.json")
    uvicorn.run(
        build_app(card, executor),
        host = "127.0.0.1",
        port = config["port"],
        log_level = "warning",
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python run_agent.py <profile>")
        print(f"Available profiles: {', '.join(PROFILES)}")
        sys.exit(1)

    profile = sys.argv[1]

    if profile not in PROFILES:
        print(f"Unknown profile: {profile}")
        print(f"Available profiles: {', '.join(PROFILES)}")
        sys.exit(1)

    main(profile)
