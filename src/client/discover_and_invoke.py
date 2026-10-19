"""Understand a request, discover an agent, pay, invoke, and optionally review."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx
from a2a.client.errors import A2AClientError
from web3.exceptions import Web3Exception
from x402.http.clients.httpx import PaymentError

from client.config import ClientPaymentPolicy
from client.feedback import prepare_reviewer, submit_interaction_feedback
from client.intent import (
    IntentConfig,
    IntentError,
    SkillMatch,
    TaskUnderstanding,
    match_skills,
    understand_task,
)
from client.invocation import invoke_plan, prepare_entry
from client.output import heading
from client.payment import PaymentPolicyError, validate_advertised_price
from erc8004.identity import LocalDeployment
from erc8004.registration import RegistrationError
from marketplace.catalog import Catalog, CatalogError, discover_agents
from x402_support.network import PaymentNetwork


def read_multiline_input() -> str:
    """Read the natural-language task before TrustRoute searches for agents."""

    print("\nDescribe the complete task. Press Enter twice when done.\n")
    lines: list[str] = []
    while True:
        line = input()
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines)


def _within_budget(
    match: SkillMatch,
    network: PaymentNetwork,
    policy: ClientPaymentPolicy,
) -> bool:
    try:
        validate_advertised_price(
            network,
            policy,
            amount_atomic=match.entry.price.amount_atomic,
            advertised_network=match.entry.price.network,
            advertised_asset=match.entry.price.asset_address,
        )
    except PaymentPolicyError:
        return False
    return True


def _print_discovery(
    understanding: TaskUnderstanding,
    catalog: Catalog,
    matches: tuple[SkillMatch, ...],
    network: PaymentNetwork,
    policy: ClientPaymentPolicy,
) -> None:
    heading("TASK UNDERSTANDING")
    print(f"Detected task type: {understanding.task_type.task_type}")
    print(f"Task type name: {understanding.task_type.name}")
    print(f"Confidence: {understanding.confidence:.2f}")
    print(f"Reason: {understanding.reason}")
    print(f"Decision source: {understanding.source}")

    heading("SEMANTIC AGENT DISCOVERY")
    print(f"Registered identities scanned: {catalog.registered_count}")
    print(f"Advertised skills compared: {len(catalog.entries)}")
    print(f"Eligible agents: {len(matches)}")
    print()

    if matches:
        print(
            f"{'ID':<5} {'AGENT':<22} {'LOCAL SKILL ID':<24} "
            f"{'MATCH':<9} {'PRICE':<16} {'BUDGET'}"
        )
        print("-" * 96)
        for match in matches:
            entry = match.entry
            price = f"{entry.price.amount} {entry.price.asset_symbol}"
            budget = "yes" if _within_budget(match, network, policy) else "no"
            print(
                f"{entry.agent.identity.agent_id:<5} "
                f"{entry.card.name:<22} "
                f"{entry.skill_id:<24} "
                f"{match.similarity:.2f}     "
                f"{price:<16} "
                f"{budget}"
            )
    else:
        print("No advertised skill is similar enough to the detected task type.")

    if catalog.skipped:
        print("\nSkipped registrations:")
        for skipped in catalog.skipped:
            print(f"  {skipped.agent_id}: {skipped.reason}")


def _choose_match(
    matches: tuple[SkillMatch, ...],
    requested_agent_id: int | None,
) -> SkillMatch:
    by_id = {match.entry.agent.identity.agent_id: match for match in matches}
    if requested_agent_id is not None:
        if requested_agent_id not in by_id:
            raise CatalogError(
                f"agent ID {requested_agent_id} is not eligible for the detected task"
            )
        return by_id[requested_agent_id]

    while True:
        try:
            raw_value = input("\nSelect an eligible agent ID: ").strip()
        except EOFError as error:
            raise CatalogError("no agent ID was selected") from error
        try:
            agent_id = int(raw_value)
        except ValueError:
            print("Please enter a numeric agent ID.")
            continue
        if agent_id in by_id:
            return by_id[agent_id]
        print(f"Choose one of: {sorted(by_id)}")


def _read_feedback_score() -> int:
    while True:
        try:
            value = input("\nQuality score from 0 to 100: ").strip()
        except EOFError as error:
            raise ValueError("no feedback score was provided") from error
        try:
            score = int(value)
        except ValueError:
            print("Please enter a whole number from 0 to 100.")
            continue
        if 0 <= score <= 100:
            return score
        print("Please enter a whole number from 0 to 100.")


async def _run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    identity_deployment = LocalDeployment.from_path(args.deployment)
    policy = ClientPaymentPolicy.from_path(args.policy)
    network = PaymentNetwork.from_path(policy.network_deployment)
    intent_config = IntentConfig.from_path(args.discovery_config)
    if network.chain_id != identity_deployment.chain_id:
        raise CatalogError("ERC-8004 and client payment policy use different chains")

    source = args.message if args.message is not None else read_multiline_input()
    if not source.strip():
        parser.error("message must not be empty")

    reviewer = None
    if args.review or args.feedback_score is not None:
        private_key = os.environ.get("TRUSTROUTE_PAYER_PRIVATE_KEY")
        if not private_key:
            raise RuntimeError("TRUSTROUTE_PAYER_PRIVATE_KEY is required")
        reviewer = prepare_reviewer(identity_deployment, policy, private_key)

    understanding = await understand_task(
        source,
        intent_config,
        override=args.task_type,
    )
    catalog = await discover_agents(args.deployment)
    matches = await match_skills(understanding, catalog.entries, intent_config)
    _print_discovery(understanding, catalog, matches, network, policy)
    if not matches:
        raise CatalogError(
            f"no eligible agents found for task type "
            f"{understanding.task_type.task_type!r}"
        )

    match = _choose_match(matches, args.agent_id)
    plan = prepare_entry(
        match.entry,
        understanding.task_type.task_type,
        identity_deployment,
        args.policy,
    )
    invocation = await invoke_plan(plan, source)

    score = args.feedback_score
    if args.review:
        score = _read_feedback_score()
    if score is not None:
        if reviewer is None:
            raise RuntimeError("feedback reviewer was not prepared")
        submit_interaction_feedback(
            reviewer,
            plan,
            invocation,
            source,
            score,
            args.evidence_dir,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--deployment",
        type=Path,
        default=Path("var/identity-deployment.json"),
        help="local ERC-8004 deployment record",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("configs/client/local-client.json"),
        help="client-owned wallet and maximum-payment policy",
    )
    parser.add_argument(
        "--discovery-config",
        type=Path,
        default=Path("configs/discovery/local.json"),
        help="task types and local Ollama discovery models",
    )
    parser.add_argument(
        "--task-type",
        help="repeatable-run override; normal users should let TrustRoute infer it",
    )
    parser.add_argument(
        "--agent-id",
        type=int,
        help="choose an eligible ID non-interactively; otherwise prompt",
    )
    parser.add_argument(
        "--message",
        help="complete task request; when omitted, read it interactively",
    )
    review_group = parser.add_mutually_exclusive_group()
    review_group.add_argument(
        "--review",
        action="store_true",
        help="prompt for and publish ERC-8004 feedback after a successful call",
    )
    review_group.add_argument(
        "--feedback-score",
        type=int,
        help="publish this 0-100 score without an interactive review prompt",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("var/evidence"),
        help="local content-addressed feedback evidence directory",
    )
    args = parser.parse_args()

    if args.agent_id is not None and args.agent_id < 0:
        parser.error("agent ID must not be negative")
    if args.feedback_score is not None and not 0 <= args.feedback_score <= 100:
        parser.error("feedback score must be between 0 and 100")

    try:
        asyncio.run(_run(args, parser))
    except PaymentPolicyError as error:
        parser.exit(1, f"Payment policy rejected the agent: {error}\n")
    except PaymentError as error:
        parser.exit(1, f"x402 payment failed: {error}\n")
    except (
        A2AClientError,
        CatalogError,
        ConnectionError,
        FileNotFoundError,
        IntentError,
        KeyError,
        RegistrationError,
        RuntimeError,
        ValueError,
        Web3Exception,
        httpx.HTTPError,
        json.JSONDecodeError,
    ) as error:
        parser.exit(1, f"Discovery or invocation failed: {error}\n")


if __name__ == "__main__":
    main()
