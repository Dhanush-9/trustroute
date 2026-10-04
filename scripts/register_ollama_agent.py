"""Register the Ollama A2A agent in the local ERC-8004 registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from erc8004 import IdentityRegistryClient, LocalDeployment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--deployment",
        type=Path,
        default=Path("var/identity-deployment.json"),
        help="deployment record written by deploy_erc8004_identity.sh",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("var/registration.json"),
        help="where to write the ERC-8004 registration document",
    )
    parser.add_argument(
        "--registration-url",
        default="http://127.0.0.1:8004/registration.json",
    )
    parser.add_argument(
        "--agent-card-url",
        default="http://127.0.0.1:8004/.well-known/agent-card.json",
    )
    args = parser.parse_args()

    client = IdentityRegistryClient(LocalDeployment.from_path(args.deployment))
    if client.deployment.chain_id != 31337:
        raise RuntimeError("this checkpoint command is restricted to a local chain")

    # register() assigns the ID. Only then can the document truthfully include
    # that ID and be linked on-chain with setAgentURI().
    identity, register_tx = client.register()
    document = {
        "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
        "name": "summarizer-ollama",
        "description": "Ollama-backed A2A text summarization agent",
        "image": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E",
        "services": [
            {
                "name": "A2A",
                "endpoint": args.agent_card_url,
                "version": "1.0",
            }
        ],
        "x402Support": False,
        "active": True,
        "registrations": [
            {
                "agentId": identity.agent_id,
                "agentRegistry": identity.registry,
            }
        ],
        "supportedTrust": [],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    uri_tx = client.set_agent_uri(identity.agent_id, args.registration_url)

    print(f"Agent:        {identity}")
    print(f"Registry:     {client.contract.address} (version {client.version()})")
    print(f"Owner:        {client.owner_of(identity.agent_id)}")
    print(f"Agent wallet: {client.agent_wallet(identity.agent_id)}")
    print(f"agentURI:     {client.token_uri(identity.agent_id)}")
    print(f"Register tx:  {register_tx}")
    print(f"URI tx:       {uri_tx}")


if __name__ == "__main__":
    main()
