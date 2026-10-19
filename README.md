# TrustRoute

TrustRoute is a prototype marketplace for AI agents. A client describes a task
in ordinary language; TrustRoute finds independently owned A2A agents registered
through ERC-8004, lets the client choose one, pays it through x402, invokes it
through A2A, and can publish interaction-bound feedback.

## Current capabilities

- Three independently owned Ollama agents, each with its own ERC-8004 identity,
  wallet, A2A AgentCard, prompts, models, and per-skill prices.
- Natural-language task understanding for summarization, translation, and code
  generation. Agents may use different local skill IDs for the same task.
- Semantic comparison of the understood task with public AgentCard skill names,
  descriptions, tags, and examples.
- Manual choice among matching agents. Automatic reputation-based ranking is
  intentionally not implemented yet.
- Client-side price, network, token, recipient, and budget checks.
- End-to-end x402 authorization, facilitator verification and settlement, and
  A2A invocation.
- Optional ERC-8004 feedback with content-addressed interaction evidence.

Reputation aggregation, automatic selection, and the Sybil/circular-payment/
cold-start experiments are the next research layer.

## Request flow

```text
natural-language request
  -> infer a task type such as translation
  -> scan ERC-8004 identities
  -> read registration documents and A2A AgentCards
  -> semantically compare advertised skills with the task type
  -> show matching agents, local skill IDs, prices, and budget status
  -> client chooses an agent
  -> unpaid A2A request receives an HTTP 402 challenge
  -> client validates and signs the payment authorization
  -> facilitator verifies; agent executes; facilitator settles
  -> client receives the A2A result and payment receipt
  -> optional evidence document and ERC-8004 feedback transaction
```

The task type is TrustRoute's simple shared label for research and feedback,
such as `translation`. The A2A skill ID belongs to the agent and does not have
to use that exact wording: one agent may advertise `translate_text` while
another advertises `language_conversion`.

## Setup

Requires Python 3.10+, Node.js with npm, and [Ollama](https://ollama.com).

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
scripts/setup_erc8004.sh
ollama pull llama3.2
ollama pull embeddinggemma
cp .env.example .env.local
```

Start the Hardhat node and copy its printed development keys into `.env.local`:

| Variable                                  | Hardhat account |
| ----------------------------------------- | --------------- |
| `TRUSTROUTE_GENERALIST_OWNER_PRIVATE_KEY` | 0               |
| `TRUSTROUTE_PAYER_PRIVATE_KEY`            | 1               |
| `TRUSTROUTE_FACILITATOR_PRIVATE_KEY`      | 2               |
| `TRUSTROUTE_TRANSLATOR_OWNER_PRIVATE_KEY` | 3               |
| `TRUSTROUTE_CODER_OWNER_PRIVATE_KEY`      | 4               |

These are public development keys. Never use them on a public network. Agent
processes need no keys, so do not source `.env.local` in agent terminals.

## Run the complete demo

Use one terminal per long-running process. Run commands from the repository
root with the virtual environment active.

### 1. Start the chain and deploy contracts

```bash
scripts/start_erc8004_node.sh
```

In a second terminal:

```bash
scripts/deploy_erc8004_identity.sh
scripts/deploy_x402_local.sh
```

### 2. Start the facilitator

```bash
source .env.local
PYTHONPATH=src python -m facilitator.run_facilitator \
  --config configs/facilitator/local.json
```

### 3. Start the three agents

Run each command in a separate terminal:

```bash
PYTHONPATH=src python -m agent.run_agent \
  --config configs/agents/ollama-generalist.json

PYTHONPATH=src python -m agent.run_agent \
  --config configs/agents/ollama-translator.json

PYTHONPATH=src python -m agent.run_agent \
  --config configs/agents/ollama-coder.json
```

| Agent               | Port | Owner     | Summarize | Translate | Code  |
| ------------------- | ---- | --------- | --------- | --------- | ----- |
| `ollama-generalist` | 8004 | account 0 | 0.028     | 0.030     | 0.032 |
| `ollama-translator` | 8005 | account 3 | 0.020     | 0.045     | 0.025 |
| `ollama-coder`      | 8006 | account 4 | 0.020     | 0.025     | 0.050 |

Prices are in trUSDC. Every skill's Ollama model is configurable independently;
all currently use `llama3.2` so the project runs with one downloaded text model.

### 4. Register the agents

The agents must be running because their registration documents are served by
their HTTP servers.

```bash
source .env.local

PYTHONPATH=src python scripts/register_agent.py \
  --config configs/agents/ollama-generalist.json
PYTHONPATH=src python scripts/register_agent.py \
  --config configs/agents/ollama-translator.json
PYTHONPATH=src python scripts/register_agent.py \
  --config configs/agents/ollama-coder.json
```

Each command registers with the owner key named in its agent configuration.
The assigned `agentId` depends on registration order.

### 5. Discover, choose, pay, and invoke

```bash
source .env.local

PYTHONPATH=src python -m client.discover_and_invoke \
  --policy configs/client/local-client.json
```

Enter a complete request such as:

```text
Translate the following sentence into Hindi: Trust requires evidence.
```

The client first understands the task, then discovers and compares agents. It
prints the match score, local skill ID, price, and budget result before asking
you to choose an eligible `agentId`.

For a repeatable, non-interactive run:

```bash
PYTHONPATH=src python -m client.discover_and_invoke \
  --message "Translate into Hindi: Trust requires evidence." \
  --agent-id 1 \
  --policy configs/client/local-client.json
```

`--agent-id` only skips the prompt; the chosen agent must still match the
understood task. `--task-type translation` is available as an experimental
ground-truth override. Normal users do not need it.

### 6. Optionally publish feedback

```bash
PYTHONPATH=src python -m client.discover_and_invoke \
  --policy configs/client/local-client.json \
  --review
```

After a successful response, enter a whole-number quality score from 0 to 100.
The client writes `var/evidence/<hash>.json` and submits `giveFeedback` from the
same wallet that paid. Without `--review`, no feedback transaction is created.
`--feedback-score 85` supplies the score non-interactively.

Evidence stores hashes of the request and response, not their raw text. It
shows that a paid interaction and its recorded bytes are linked; it cannot
prove that the reviewer's quality judgment is honest.

## Deliberate rejection examples

These fail before a payment authorization is signed:

```bash
# The selected agent must be one of the semantically matching candidates.
PYTHONPATH=src python -m client.discover_and_invoke \
  --message "Translate this into Hindi: hello" \
  --agent-id 999 \
  --policy configs/client/local-client.json

# Matching offers above this policy's cap are displayed as over budget.
PYTHONPATH=src python -m client.discover_and_invoke \
  --message "Translate this paragraph into Hindi: hello" \
  --policy configs/client/low-budget.json
```

## Direct A2A test fixture

`fast-test`, `accurate-test`, and `new-test` are deterministic, unregistered
agents for protocol checks without a chain or Ollama:

```bash
PYTHONPATH=src python -m agent.run_agent \
  --config configs/agents/fast-test.json

PYTHONPATH=src python -m client.demo_client \
  --url http://127.0.0.1:8001 --skill summarize_text
```

This low-level test intentionally accepts an exact local skill ID. It is not
the marketplace discovery command.

## Configuration

| Location                   | Contents |
| -------------------------- | -------- |
| `configs/agents/`          | Agent servers, public skills, models, prompts, prices, recipients, and owner-key variable names |
| `configs/client/`          | Payer address and maximum payment |
| `configs/discovery/`       | Task types, thresholds, and local Ollama routing/embedding models |
| `configs/facilitator/`     | Facilitator URL, signer address, and network |
| `var/*.json`               | Generated deployment data, ignored by Git |
| `var/evidence/`            | Local content-addressed interaction evidence |
| `.env.local`               | Development private keys, ignored by Git |

## Project layout

- `src/agent/`: configuration, AgentCards, skill dispatch, executors, seller
  payment policy, and HTTP server
- `src/client/`: task understanding, semantic matching, payment policy,
  invocation, and feedback
- `src/marketplace/`: ERC-8004 event scan, registration resolution, and
  AgentCard validation
- `src/facilitator/`: x402 verification and settlement service
- `src/erc8004/`: Identity and Reputation Registry adapters
- `src/x402_support/`: shared network and token data
- `infra/`, `scripts/`: contracts, setup, deployment, and registration
- `teach/`: beginner-friendly execution flow and design decisions
