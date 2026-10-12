# TrustRoute
 
TrustRoute is a prototype for identity-rooted discovery, payment and invocation
of A2A agents. An agent is registered in an ERC-8004 identity registry, a client
resolves it from its `agentId`, pays for the call through x402, and receives the
result over A2A.
 
## Status
 
Working: a real Ollama-backed agent is registered on a local chain, resolved by
its `agentId`, paid with a local test token, and invoked end to end.
 
Not yet implemented: registry indexing, multi-agent selection, reputation
feedback and attack experiments. The client currently resolves one known
`agentId`.
 
## Architecture
 
```text
ERC-8004 Identity Registry
  -> agentURI
  -> registration document
  -> A2A AgentCard
  -> paid A2A endpoint
 
Client                         Agent                         Facilitator
------                         -----                         -----------
payer wallet                   A2A executor                  settlement key
independent maximum budget     price and recipient           /supported
checks ERC-8004 agentWallet    x402 resource server          /verify
signs authorization            invokes Ollama                /settle
```
 
Each role owns only what it needs. The client refuses an x402 offer whose
`payTo` differs from the agent's ERC-8004 `agentWallet`, and its budget is
independent of the price the agent asks.
 
## Requirements
 
- Python 3.10+
- Node.js and npm (for the local Hardhat chain)
- [Ollama](https://ollama.com)
## Setup
 
From the repository root:
 
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
scripts/setup_erc8004.sh
ollama pull llama3.2
```
 
### Keys
 
Private keys live only in an ignored `.env.local` file:
 
```bash
cp .env.example .env.local
```
 
When the Hardhat node starts (step 1 below) it prints funded development
accounts. Fill `.env.local` with:
 
| Variable                             | Hardhat account |
| ------------------------------------ | --------------- |
| `TRUSTROUTE_AGENT_OWNER_PRIVATE_KEY` | 0               |
| `TRUSTROUTE_PAYER_PRIVATE_KEY`       | 1               |
| `TRUSTROUTE_FACILITATOR_PRIVATE_KEY` | 2               |
 
These are public development keys. Never use them, or fund their addresses, on a
public network.
 
## Run the demo
 
Use one terminal per step, each in the repository root with the virtual
environment active. Run `source .env.local` only where shown, so that the agent
process never holds the payer or facilitator keys.
 
**1. Start the local chain**
 
```bash
scripts/start_erc8004_node.sh
```
 
**2. Deploy the contracts**
 
```bash
scripts/deploy_erc8004_identity.sh
scripts/deploy_x402_local.sh
```
 
The second script deploys a valueless test token (trUSDC), mints 100 to the
payer, and writes chain and token details to `var/payment-network.json`.
 
**3. Start the facilitator**
 
```bash
source .env.local
PYTHONPATH=src python -m facilitator.run_facilitator \
  --config configs/facilitator/local.json
```
 
It serves `GET /supported`, `POST /verify` and `POST /settle`, and must be
running before the agent starts.
 
**4. Start the agent**
 
```bash
PYTHONPATH=src python -m agent.run_agent \
  --config configs/agents/ollama-summarizer.json
```
 
**5. Register the agent**
 
```bash
source .env.local
PYTHONPATH=src python scripts/register_agent.py \
  --config configs/agents/ollama-summarizer.json
```
 
This validates the live AgentCard, registers the agent with the owner's key,
writes its registration document, sets the on-chain `agentURI`, and checks that
owner, `agentWallet` and payment recipient match. It prints the assigned
`agentId`.
 
**6. Resolve, pay and invoke**
 
```bash
source .env.local
PYTHONPATH=src python -m client.resolve_and_invoke \
  --agent-id 0 \
  --policy configs/client/local-client.json \
  --message "ERC-8004 identifies, x402 pays, and A2A invokes this agent."
```
 
Use the `agentId` printed in step 5. The client:
 
```text
reads owner, agentWallet and agentURI from ERC-8004
  -> validates the registration document and resolves the AgentCard
  -> sends an unpaid request and receives HTTP 402
  -> checks network, token, maximum amount and recipient
  -> signs one EIP-3009 authorization and retries
  -> agent verifies with the facilitator, runs Ollama, then settles
  -> client prints the response and the settlement transaction
```
 
### Budget rejection
 
This policy allows less than the agent's price (20,000 against 30,000 atomic
units):
 
```bash
source .env.local
PYTHONPATH=src python -m client.resolve_and_invoke \
  --agent-id 0 \
  --policy configs/client/low-budget.json \
  --message "This request should be rejected before signing."
```
 
No authorization is signed, no payment is made, and balances do not change.

## Configuration
 
| Location                | Contents                                                      | Owner          |
| ----------------------- | ------------------------------------------------------------- | -------------- |
| `var/payment-network.json` | Chain and token details (generated, ignored)               | Deploy script  |
| `configs/agents/`       | Executor, skill, price, recipient, registration document path | Agent operator |
| `configs/client/`       | Payer address and maximum payment                             | Client         |
| `configs/facilitator/`  | Facilitator URL, signer address, network reference            | Facilitator    |
| `.env.local`            | Private keys (ignored)                                        | Each runtime   |
 
Public addresses are configuration, not secrets. Private keys never go in JSON
files or the deployment record.
 
## Layout
 
- `src/agent/`: AgentCard, executors, operator config, seller payment policy,
  A2A server
- `src/client/`: resolution, budget policy, payer signing, A2A invocation
- `src/facilitator/`: x402 verification and settlement service
- `src/erc8004/`: Identity Registry client and registration documents
- `src/x402_support/`: shared network and token data
- `configs/`: non-secret, role-specific configuration
- `infra/`: Solidity token contract and deployment entry points
- `scripts/`: setup, deployment and registration commands
