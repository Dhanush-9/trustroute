# TrustRoute

TrustRoute is a prototype for identity-rooted discovery, payment and invocation
of A2A agents. Agents register in an ERC-8004 Identity Registry, advertise
skills through A2A AgentCards, accept x402 payments, and return results over
A2A.

## Status

Working: three independently owned Ollama agents are discovered from ERC-8004
events, filtered by A2A skill, manually selected, paid at a skill-specific x402
price, and invoked over A2A.

Not yet implemented: automatic ranking, reputation feedback and attack
experiments.

## How it works

```text
skill
  -> scan ERC-8004 Registered events
  -> registration documents -> AgentCards
  -> show eligible agents and per-skill prices -> user chooses agentId
  -> unpaid A2A request -> HTTP 402 (x402)
  -> client checks advertised price, network, token, budget and recipient
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

| Agent               | Port | Owner     | Summarize | Translate | Code  |
| ------------------- | ---- | --------- | --------- | --------- | ----- |
| `ollama-generalist` | 8004 | account 0 | 0.028     | 0.030     | 0.032 |
| `ollama-translator` | 8005 | account 3 | 0.020     | 0.045     | 0.025 |
| `ollama-coder`      | 8006 | account 4 | 0.020     | 0.025     | 0.050 |

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

**5. Discover, choose and invoke**

```bash
source .env.local

PYTHONPATH=src python -m client.discover_and_invoke \
  --skill translate_text \
  --policy configs/client/local-client.json
```

The client scans registry events, validates registration documents and
AgentCards, shows all eligible agents and their prices, then prompts for an
`agentId`. It asks for task input only after the selection and payment policy
have been validated.

For repeatable scripts, choose a known ID directly:

```bash
PYTHONPATH=src python -m client.resolve_and_invoke \
  --agent-id <ID> --skill translate_text \
  --policy configs/client/local-client.json \
  --message "Translate into Hindi: Trust requires evidence."
```

**Rejections** (no authorization is signed, no balance changes):

```bash
source .env.local

# no registered AgentCard advertises this skill
PYTHONPATH=src python -m client.discover_and_invoke \
  --skill unknown_skill \
  --policy configs/client/local-client.json

# every translation candidate exceeds this client's 0.02 trUSDC maximum
PYTHONPATH=src python -m client.discover_and_invoke \
  --skill translate_text \
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
| `configs/agents/`          | server, skills, per-skill prices, executors, recipient and owner key variable |
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
- `src/marketplace/`: event-based catalog and AgentCard validation
- `src/x402_support/`: shared network and token data
- `infra/`, `scripts/`: contracts, deployment, setup and registration
