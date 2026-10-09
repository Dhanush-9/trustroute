import argparse
import json
from pathlib import Path

from erc8004.identity import IdentityRegistryClient, LocalDeployment
from erc8004.registration import REGISTRATION_TYPE


# Register the local Ollama agent in ERC-8004

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register the Ollama A2A agent in local ERC-8004 registry"
    )

    parser.add_argument(
        "--deployment",
        type=Path,
        default=Path("var/identity-deployment.json"),
        help="Identity Registry deployment file written by deploy_erc8004_identity.sh",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path("var/registration.json"),
        help="Path where registration.json will be created",
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

    # Connect to the deployed Identity Registry

    client = IdentityRegistryClient(
        LocalDeployment.from_path(args.deployment)
    )

    if client.deployment.chain_id != 31337:
        raise RuntimeError(
            "this checkpoint command is restricted to a local chain"
        )

    # Register the agent and obtain its agentId
    identity, register_tx = client.register()
    
    #Create registration.json using the assigned agentId
    document = {
        "type": REGISTRATION_TYPE,
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

    # Save registration.json
    args.output.parent.mkdir(
        parents=True,
        exist_ok=True
    
    )
    args.output.write_text(
        json.dumps(document, indent=2) + "\n",
        encoding="utf-8"
    )

    #Store the registration.json URL on-chain
    uri_tx = client.set_agent_uri(
        identity.agent_id, args.registration_url
    )

    #Print registration result
    print(f"Agent:        {identity}")
    print(f"Registry:     {client.contract.address} (version {client.version()})")
    print(f"Owner:        {client.owner_of(identity.agent_id)}")
    print(f"Agent wallet: {client.agent_wallet(identity.agent_id)}")
    print(f"agentURI:     {client.token_uri(identity.agent_id)}")
    print(f"Register tx:  {register_tx}")
    print(f"URI tx:       {uri_tx}")


if __name__ == "__main__":
    main()
