"""Start one TrustRoute A2A agent from an operator-owned configuration file."""

import argparse
from pathlib import Path

import uvicorn

from agent.cards import build_agent_card, marketplace_extension
from agent.config import AgentConfig, SkillConfig
from agent.executor import (
    DeterministicSummarizer,
    OllamaTextExecutor,
    SkillDispatcher,
)
from agent.payment import build_payment_gate
from agent.server import build_app
from x402_support.network import PaymentNetwork


def _build_skill_executor(agent_name: str, skill: SkillConfig):
    executor = skill.executor
    if executor.executor_type == "ollama":
        return OllamaTextExecutor(
            agent_name=agent_name,
            skill_id=skill.skill_id,
            model=executor.model or "",
            host=executor.host or "",
            system_prompt=executor.system_prompt or "",
        )

    return DeterministicSummarizer(
        agent_name=agent_name,
        latency_ms=executor.latency_ms or 0,
        retention_ratio=(
            executor.retention_ratio
            if executor.retention_ratio is not None
            else 1
        ),
    )


def _build_executor(config: AgentConfig) -> SkillDispatcher:
    return SkillDispatcher(
        {
            skill.skill_id: _build_skill_executor(config.name, skill)
            for skill in config.skills
        }
    )


def run(config_path: Path) -> None:
    config = AgentConfig.from_path(config_path)
    payment_gate = None

    if config.payment is not None:
        network = PaymentNetwork.from_path(config.payment.network_deployment)
        advertised_prices = {
            skill.skill_id: {
                "amount": network.display_amount(skill.price_atomic or "0"),
                "amount_atomic": skill.price_atomic or "0",
                "asset_symbol": network.asset_symbol,
                "asset_address": network.asset,
                "network": network.network,
            }
            for skill in config.skills
        }
        listing = marketplace_extension(
            skill_prices=advertised_prices,
            authority="agent-payment-config",
        )
        payment_gate = build_payment_gate(
            network,
            config.payment,
            config.skill_prices,
        )
    elif config.test_listing is not None:
        advertised_prices = {
            skill.skill_id: {
                "amount": config.test_listing.amount,
                "asset_symbol": config.test_listing.asset,
            }
            for skill in config.skills
        }
        listing = marketplace_extension(
            skill_prices=advertised_prices,
            authority=config.test_listing.authority,
        )
    else:
        listing = None

    card = build_agent_card(
        name=config.name,
        description=config.description,
        url=f"{config.base_url}/",
        skills=config.skills,
        listing=listing,
        version=config.version,
    )
    registration_path = (
        config.registration.document_path if config.registration is not None else None
    )
    app = build_app(
        card,
        _build_executor(config),
        skill_ids=config.skill_ids,
        registration_document_path=registration_path,
        payment_gate=payment_gate,
    )

    print("\n" + "=" * 68)
    print("AGENT STARTUP")
    print("=" * 68)
    print(f"Agent: {config.name}")
    print(f"AgentCard: {config.agent_card_url}")
    print(f"Skills: {list(config.skill_ids)}")
    print("\nSKILLS AND PRICING")
    for skill in config.skills:
        model = skill.executor.model or skill.executor.executor_type
        if config.payment is not None:
            price = network.display_amount(skill.price_atomic or "0")
            print(f"  {skill.skill_id}: {model}, {price} {network.asset_symbol}")
        else:
            print(f"  {skill.skill_id}: {model}")
    if config.payment is not None:
        print("\nPAYMENT AND REGISTRATION")
        print(f"Payment recipient: {config.payment.recipient}")
        print(f"Facilitator: {config.payment.facilitator_url}")
        print(f"Registration file: {registration_path}")

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level="warning",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="agent configuration file",
    )
    args = parser.parse_args()

    try:
        run(args.config)
    except (ConnectionError, FileNotFoundError, KeyError, ValueError) as error:
        parser.exit(1, f"Agent startup failed: {error}\n")


if __name__ == "__main__":
    main()
