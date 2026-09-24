# TrustRoute

This repository currently contains a small summarization demo: four agent profiles (`fast`, `accurate`, `new`, and `ollama`) and a client that reads their AgentCards and sends text for summarization. The first three profiles use controlled, repeatable behavior; `ollama` uses a locally running Ollama model. The prices in the cards are discovery metadata, not payment requests.

## Setup

Requires Python 3.10+ and an activated virtual environment. From the project root:

```bash
python -m pip install a2a-sdk[http-server] httpx uvicorn
```

For the `ollama` profile, run Ollama locally and make the `llama3.2` model available. You can override the defaults with `OLLAMA_HOST` and `OLLAMA_MODEL`.

## Run the demo

Open two terminals in the project root and activate the virtual environment in each. In the first terminal:

```bash
cd src
python -m agent.run_agent fast
```

In the second terminal:

```bash
cd src
python -m client.demo_client \
  --url http://localhost:8001 \
  --message "TrustRoute uses A2A for agent communication."
```

Omit `--message` to paste multiline text interactively and press Enter twice
to submit it. Start `accurate`, `new`, or `ollama` instead to try another
profile. Their local ports are 8002, 8003, and 8004 respectively.

## What the client does

The client starts with a known service location. It then performs this A2A flow:

```text
explicit base URL
    1. GET /.well-known/agent-card.json
    2. inspect the advertised interface and skills
    3. construct SendMessageRequest
    4. send the JSON-RPC request
    5. receive an A2A message
    6. display its context ID, task ID, and text
```

This is **AgentCard resolution**, not marketplace discovery. Resolution asks
an already-known service for its card. Discovery would first determine which
agent and endpoint should be considered; ERC-8004 will provide that connection later.

The card's USDC price is also self-declared discovery metadata. It is not an
x402 payment requirement and no payment occurs in this checkpoint.

## Layout

- `src/agent/cards.py`: builds A2A AgentCards and marketplace discovery metadata.
- `src/agent/executor.py`: controlled and Ollama backed summarizers.
- `src/agent/server.py`: creates the A2A HTTP application.
- `src/agent/run_agent.py`: starts one selected agent profile.
- `src/client/demo_client.py`: discovers a card and invokes the agent.

This demo does not yet implement ERC-8004 registration, x402 settlement, or reputation based selection.
