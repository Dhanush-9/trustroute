# TrustRoute

This repository currently contains a small summarization demo: four agent profiles (`fast`, `accurate`, `new`, and `ollama`) and a client that reads their AgentCards and sends text for summarization. The first three profiles use controlled, repeatable behavior; `ollama` uses a locally running Ollama model. The prices in the cards are discovery metadata, not payment requests.

## Setup

Requires Python 3.10+ and an activated virtual environment. From the project root:

```bash
python -m pip install a2a-sdk[http-server] uvicorn
```

For the `ollama` profile, run Ollama locally and make the `llama3.2` model available. You can override the defaults with `OLLAMA_HOST` and `OLLAMA_MODEL`.

## Run the demo

Open two terminals in the project root and activate the virtual environment in each. In the first terminal:

```bash
cd src
python agent/run_agent.py fast
```

In the second terminal:

```bash
cd src
python -m client.demo_client fast
```

Paste text and press Enter twice to submit it. Replace `fast` in both commands with `accurate`, `new`, or `ollama` to try another profile. Each profile uses a different local port (8001–8004).

## Layout

- `src/agent/cards.py`: builds A2A AgentCards and marketplace discovery metadata.
- `src/agent/executor.py`: controlled and Ollama backed summarizers.
- `src/agent/server.py`: creates the A2A HTTP application.
- `src/agent/run_agent.py`: starts one selected agent profile.
- `src/client/demo_client.py`: discovers a card and invokes the agent.

This demo does not yet implement ERC-8004 registration, x402 settlement, or reputation based selection.
