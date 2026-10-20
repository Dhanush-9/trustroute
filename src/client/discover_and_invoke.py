"""Understand a request, discover an agent, pay, invoke, and optionally review."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections import Counter
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
from client.output import demo_pause_seconds, heading, set_demo_pace
from client.payment import PaymentPolicyError, validate_advertised_price
from client.selection import RankedCandidate, rank_candidates, select_candidate
from erc8004.identity import LocalDeployment
from erc8004.registration import RegistrationError
from marketplace.catalog import Catalog, CatalogError, discover_agents
from reputation.views import (
    AgentReputation,
    ReputationScore,
    calculate_reputation_views,
)
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


def _print_understanding(understanding: TaskUnderstanding) -> None:
    print(f"Detected task type: {understanding.task_type.task_type}")
    print(f"Task type name: {understanding.task_type.name}")
    print(f"Confidence: {understanding.confidence:.2f}")
    print(f"Reason: {understanding.reason}")
    print(f"Decision source: {understanding.source}")


def _print_discovery(
    catalog: Catalog,
    matches: tuple[SkillMatch, ...],
    network: PaymentNetwork,
    policy: ClientPaymentPolicy,
) -> None:
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


def _format_reputation(score: ReputationScore) -> str:
    if score.average is None:
        return "N/A (0)"
    value = f"{score.average:.2f}".rstrip("0").rstrip(".")
    return f"{value} ({score.count})"


def _print_reputation(
    understanding: TaskUnderstanding,
    matches: tuple[SkillMatch, ...],
    reputation: dict[int, AgentReputation],
) -> None:
    print(f"Task type: {understanding.task_type.task_type}")
    print("All three columns use the same on-chain feedback history.")
    print()
    print(
        f"{'ID':<5} {'AGENT':<22} {'RAW':<13} {'TASK-TYPED':<13} "
        f"{'VERIFIED':<13} {'EXCLUDED'}"
    )
    print("-" * 88)
    for match in matches:
        agent_id = match.entry.agent.identity.agent_id
        views = reputation[agent_id]
        print(
            f"{agent_id:<5} "
            f"{match.entry.card.name:<22} "
            f"{_format_reputation(views.raw):<13} "
            f"{_format_reputation(views.task_typed):<13} "
            f"{_format_reputation(views.interaction_verified):<13} "
            f"{len(views.verification_rejections)}"
        )

    reasons = Counter(
        rejection.reason
        for match in matches
        for rejection in reputation[
            match.entry.agent.identity.agent_id
        ].verification_rejections
    )
    if reasons:
        print("\nWhy task-typed feedback was excluded from the verified view:")
        for reason, count in reasons.most_common():
            print(f"  {count} x {reason}")
    print("\nN/A means no feedback qualified; it is not a score of zero.")


def _print_selection(
    ranked: tuple[RankedCandidate, ...],
    selected: RankedCandidate,
    policy: ClientPaymentPolicy,
    override_used: bool,
) -> None:
    settings = policy.selection
    print(
        "Weights: "
        f"verified reputation {settings.reputation_weight:.0%}, "
        f"semantic match {settings.semantic_weight:.0%}, "
        f"price {settings.price_weight:.0%}"
    )
    print(
        f"Cold start: neutral prior {settings.prior_score:g}/100 with "
        f"weight {settings.prior_weight:g}; exploration bonus up to "
        f"{settings.cold_start_bonus:.3f}"
    )
    print("Only affordable candidates participate in this ranking.\n")
    print(
        f"{'RANK':<6} {'ID':<5} {'AGENT':<22} {'VERIFIED':<13} "
        f"{'TRUST':<8} {'MATCH':<8} {'PRICE':<14} {'BONUS':<8} {'FINAL'}"
    )
    print("-" * 112)
    for position, candidate in enumerate(ranked, start=1):
        entry = candidate.match.entry
        marker = " <- selected" if candidate.agent_id == selected.agent_id else ""
        print(
            f"{position:<6} {candidate.agent_id:<5} {entry.card.name:<22} "
            f"{_format_reputation(candidate.reputation.interaction_verified):<13} "
            f"{candidate.reputation_estimate:<8.2f} "
            f"{candidate.match.similarity:<8.2f} "
            f"{entry.price.amount + ' ' + entry.price.asset_symbol:<14} "
            f"{candidate.cold_start_bonus:<8.3f} "
            f"{candidate.total_score:.3f}{marker}"
        )

    automatic = ranked[0]
    if override_used:
        print(
            f"\nExperiment override selected agent {selected.agent_id}; automatic "
            f"winner would be agent {automatic.agent_id}."
        )
    else:
        print(
            f"\nAutomatic winner: agent {selected.agent_id} "
            f"({selected.match.entry.card.name})."
        )
    print(
        "Reason: highest visible final score after combining smoothed verified "
        "reputation, semantic relevance, price, and the cold-start bonus."
    )


def _elapsed_ms(started: float, paused_before: float | None = None) -> int:
    elapsed = time.perf_counter() - started
    if paused_before is not None:
        elapsed -= demo_pause_seconds() - paused_before
    return round(max(elapsed, 0) * 1000)


def _print_timings(
    timings: dict[str, int],
    total_ms: int,
    presentation_pause_ms: int,
) -> None:
    print("\nTIMING SUMMARY")
    print(f"{'STAGE':<30} {'DURATION':>12}")
    print("-" * 43)
    for name, duration in timings.items():
        print(f"{name:<30} {duration:>9} ms")
    print("-" * 43)
    print(f"{'Total to A2A response':<30} {total_ms:>9} ms")
    if presentation_pause_ms:
        print(f"{'Demo pauses (excluded)':<30} {presentation_pause_ms:>9} ms")


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
    workflow_started = time.perf_counter()
    timings: dict[str, int] = {}

    reviewer = None
    if args.review or args.feedback_score is not None:
        private_key = os.environ.get("TRUSTROUTE_PAYER_PRIVATE_KEY")
        if not private_key:
            raise RuntimeError("TRUSTROUTE_PAYER_PRIVATE_KEY is required")
        reviewer = prepare_reviewer(identity_deployment, policy, private_key)

    heading("TASK UNDERSTANDING")
    started = time.perf_counter()
    understanding = await understand_task(
        source,
        intent_config,
        override=args.task_type,
    )
    timings["understanding"] = _elapsed_ms(started)
    _print_understanding(understanding)

    heading("SEMANTIC AGENT DISCOVERY")
    started = time.perf_counter()
    catalog = await discover_agents(args.deployment)
    timings["registry discovery"] = _elapsed_ms(started)
    started = time.perf_counter()
    matches = await match_skills(understanding, catalog.entries, intent_config)
    timings["semantic matching"] = _elapsed_ms(started)
    _print_discovery(catalog, matches, network, policy)
    if not matches:
        raise CatalogError(
            f"no eligible agents found for task type "
            f"{understanding.task_type.task_type!r}"
        )

    agents_by_id = {
        entry.agent.identity.agent_id: entry.agent
        for entry in catalog.entries
    }
    heading("ERC-8004 REPUTATION VIEWS")
    started = time.perf_counter()
    reputation = calculate_reputation_views(
        identity_deployment,
        network,
        tuple(agents_by_id.values()),
        understanding.task_type.task_type,
        args.evidence_dir,
    )
    timings["reputation verification"] = _elapsed_ms(started)
    _print_reputation(understanding, matches, reputation)

    heading("EXPLAINABLE AGENT SELECTION")
    ranked = rank_candidates(matches, reputation, network, policy)
    selected = select_candidate(ranked, args.agent_id)
    _print_selection(
        ranked,
        selected,
        policy,
        override_used=args.agent_id is not None,
    )
    match = selected.match
    plan = prepare_entry(
        match.entry,
        understanding.task_type.task_type,
        identity_deployment,
        args.policy,
    )
    started = time.perf_counter()
    paused_before_invocation = demo_pause_seconds()
    invocation = await invoke_plan(plan, source)
    timings["paid A2A invocation"] = _elapsed_ms(
        started,
        paused_before_invocation,
    )
    total_to_response_ms = _elapsed_ms(workflow_started, 0.0)

    score = args.feedback_score
    if args.review:
        score = _read_feedback_score()
    if score is not None:
        if reviewer is None:
            raise RuntimeError("feedback reviewer was not prepared")
        heading("ERC-8004 FEEDBACK")
        submit_interaction_feedback(
            reviewer,
            plan,
            invocation,
            source,
            score,
            args.evidence_dir,
        )
    presentation_pause_ms = round(demo_pause_seconds() * 1000)
    _print_timings(timings, total_to_response_ms, presentation_pause_ms)


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
        help="client-owned payment and automatic-selection policy",
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
        help="override automatic selection with an affordable eligible agent ID",
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
    parser.add_argument(
        "--demo-pace",
        type=float,
        metavar="SECONDS",
        help="presentation-only pause before each section heading",
    )
    args = parser.parse_args()

    if args.agent_id is not None and args.agent_id < 0:
        parser.error("agent ID must not be negative")
    if args.feedback_score is not None and not 0 <= args.feedback_score <= 100:
        parser.error("feedback score must be between 0 and 100")
    if args.demo_pace is not None and args.demo_pace < 0:
        parser.error("demo pace must not be negative")
    set_demo_pace(args.demo_pace or 0.0)

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
