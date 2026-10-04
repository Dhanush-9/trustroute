# TrustRoute

This repository contains a small A2A summarization demo and a local ERC-8004 identity slice. Four agent profiles (`fast`, `accurate`, `new`, and `ollama`) expose the same A2A interface. The first three use controlled, repeatable behavior; `ollama` uses a locally running model. Checkpoint 2A registers the Ollama agent in an actual official ERC-8004 Identity Registry deployed on a local Hardhat chain.

## Setup

Requires Python 3.10+. Create a virtual environment and install the pinned
runtime dependencies from the project root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
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

## Checkpoint 2A: local ERC-8004 identity

This checkpoint adds identity registration without yet changing the A2A client. Its visible result is one real on-chain ERC-721 identity whose `agentURI` points to a registration document served by the Ollama agent.

### One-time setup

```bash
scripts/setup_erc8004.sh
```

### Run the identity flow

Use four terminals in the repository root. First start the local chain:

```bash
scripts/start_erc8004_node.sh
```

Deploy the official Identity Registry proxy and implementation:

```bash
scripts/deploy_erc8004_identity.sh
```

Start the Ollama-backed A2A service:

```bash
cd src
python -m agent.run_agent ollama
```

Finally, from the repository root, mint the identity, generate its registration document, and set its on-chain URI:

```bash
PYTHONPATH=src python scripts/register_ollama_agent.py
```

## Layout

- `src/agent/cards.py`: builds A2A AgentCards and marketplace discovery metadata.
- `src/agent/executor.py`: controlled and Ollama backed summarizers.
- `src/agent/server.py`: creates the A2A HTTP application.
- `src/agent/run_agent.py`: starts one selected agent profile.
- `src/client/demo_client.py`: discovers a card and invokes the agent.
- `src/erc8004/identity.py`: minimal client for the official Identity Registry.
- `infra/erc8004/`: deployment entry point and protocol notes.
- `scripts/`: reproducible local-chain setup, deployment, and registration commands.
- `requirements.txt`: pins the direct runtime dependencies used by the demo.

