# TrustRoute

TrustRoute is a prototype for identity-rooted discovery, payment and invocation
of A2A agents. Agents register in an ERC-8004 Identity Registry, advertise
skills through A2A AgentCards, accept x402 payments, and return results over
A2A.

## Status

Working: three independently owned Ollama agents, each offering three skills,
registered on a local chain and invoked with a client-chosen agent and skill,
paid in a local test token.

Not yet implemented: registry indexing, agent selection, per-skill pricing,
reputation feedback and attack experiments.

## How it works

```text
agentId + skill
  -> ERC-8004 owner, agentWallet and agentURI
  -> registration document -> AgentCard
  -> unpaid A2A request -> HTTP 402 (x402)
  -> client checks network, token, budget and recipient, then signs
  -> facilitator verifies; agent runs the skill; facilitator settles
  -> client receives the A2A reply and the settlement transaction
```

- The skill is sent in the `X-TrustRoute-Skill` header and in A2A request
  metadata. The agent rejects a missing, unknown or mismatched skill before it
  issues a payment challenge.
- The client refuses any offer whose `payTo` differs from the agent's ERC-8004
  `agentWallet`, and its budget is independent of the agent's price.

## Setup

Requires Python 3.10+, Node.js with npm, and [Ollama](https://ollama.com).

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
scripts/setup_erc8004.sh
ollama pull llama3.2
cp .env.example .env.local
```

Start the Hardhat node (step 1 below) and copy its printed development keys
into `.env.local`:

| Variable                                  | Hardhat account |
| ----------------------------------------- | --------------- |
| `TRUSTROUTE_GENERALIST_OWNER_PRIVATE_KEY` | 0               |
| `TRUSTROUTE_PAYER_PRIVATE_KEY`            | 1               |
| `TRUSTROUTE_FACILITATOR_PRIVATE_KEY`      | 2               |
| `TRUSTROUTE_TRANSLATOR_OWNER_PRIVATE_KEY` | 3               |
| `TRUSTROUTE_CODER_OWNER_PRIVATE_KEY`      | 4               |

These are public development keys. Never use them on a public network. Agent
processes need no keys, so do not `source .env.local` for them.

## Run

Use one terminal per long-running process, each in the repository root with
the virtual environment active.

**1. Chain and contracts**

```bash
scripts/start_erc8004_node.sh
```

In another terminal:

```bash
scripts/deploy_erc8004_identity.sh
scripts/deploy_x402_local.sh
```

**2. Facilitator**

```bash
source .env.local

PYTHONPATH=src python -m facilitator.run_facilitator \
  --config configs/facilitator/local.json
```

**3. Agents** (one terminal each)

```bash
PYTHONPATH=src python -m agent.run_agent \
  --config configs/agents/ollama-generalist.json

PYTHONPATH=src python -m agent.run_agent \
  --config configs/agents/ollama-translator.json

PYTHONPATH=src python -m agent.run_agent \
  --config configs/agents/ollama-coder.json
```

| Agent               | Port | Owner     | Price (all skills) |
| ------------------- | ---- | --------- | ------------------ |
| `ollama-generalist` | 8004 | account 0 | 0.03 trUSDC        |
| `ollama-translator` | 8005 | account 3 | 0.025 trUSDC       |
| `ollama-coder`      | 8006 | account 4 | 0.04 trUSDC        |

Each agent offers `summarize_text`, `translate_text` and `generate_code`, with
its own model and prompt per skill (all `llama3.2` for now).

**4. Register** (agents must be running)

```bash
source .env.local

PYTHONPATH=src python scripts/register_agent.py \
  --config configs/agents/ollama-generalist.json

PYTHONPATH=src python scripts/register_agent.py \
  --config configs/agents/ollama-translator.json

PYTHONPATH=src python scripts/register_agent.py \
  --config configs/agents/ollama-coder.json
```

Each command registers with the owner key named in that agent's config and
prints the assigned `agentId`. Note the IDs; they depend on registration order.

**5. Invoke**

```bash
source .env.local

PYTHONPATH=src python -m client.resolve_and_invoke \
  --agent-id <ID> \
  --skill translate_text \
  --policy configs/client/local-client.json
```

The client prompts for the text to send. Change `--agent-id` and `--skill` to
use another agent or skill. The output shows the resolved identity, the
advertised and authoritative price, recipient and budget checks, the settlement
transaction, balance changes, A2A context and task IDs, and the response.

**Rejections** (no authorization is signed, no balance changes):

```bash
source .env.local

# skill the agent does not advertise
PYTHONPATH=src python -m client.resolve_and_invoke \
  --agent-id <ID> --skill unknown_skill \
  --policy configs/client/local-client.json

# price above the client's maximum (0.02 trUSDC)
PYTHONPATH=src python -m client.resolve_and_invoke \
  --agent-id <ID> --skill summarize_text \
  --policy configs/client/low-budget.json
```

## Test fixtures

`fast-test`, `accurate-test` and `new-test` are deterministic, unregistered
agents for repeatable tests. They advertise only `summarize_text` and need no
chain:

```bash
PYTHONPATH=src python -m agent.run_agent \
  --config configs/agents/fast-test.json

PYTHONPATH=src python -m client.demo_client \
  --url http://127.0.0.1:8001 --skill summarize_text
```

## Configuration

| Location                   | Contents                                              |
| -------------------------- | ----------------------------------------------------- |
| `configs/agents/`          | server, skills and executors, price, recipient, owner key variable |
| `configs/client/`          | payer address, maximum payment                        |
| `configs/facilitator/`     | service URL, signer address, network                  |
| `var/*.json`               | generated deployment data (ignored by Git)            |
| `.env.local`               | private keys (ignored by Git)                         |

## Layout

- `src/agent/`: config, AgentCard, skill routing and dispatch, executors,
  seller payment policy, server
- `src/client/`: resolution, budget policy, payer signing, invocation
- `src/facilitator/`: x402 verification and settlement service
- `src/erc8004/`: Identity Registry client and registration documents
- `src/x402_support/`: shared network and token data
- `infra/`, `scripts/`: contracts, deployment, setup and registration