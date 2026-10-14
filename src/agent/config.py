"""Configuration models for one independently operated A2A agent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from web3 import Web3


def _require_object(data: dict, field: str) -> dict:
    value = data.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"agent configuration field '{field}' must be an object")
    return value


def _require_string(data: dict, field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"agent configuration field '{field}' must be a string")
    return value


def _require_http_url(value: str, field: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"agent configuration field '{field}' must be an HTTP URL")
    return value.rstrip("/")


def _resolve_path(config_path: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (config_path.parent / path).resolve()


@dataclass(frozen=True, slots=True)
class ExecutorConfig:
    """Implementation used for one advertised skill."""

    executor_type: str
    model: str | None = None
    host: str | None = None
    system_prompt: str | None = None
    latency_ms: int | None = None
    retention_ratio: float | None = None


@dataclass(frozen=True, slots=True)
class SkillConfig:
    skill_id: str
    name: str
    description: str
    tags: tuple[str, ...]
    executor: ExecutorConfig


@dataclass(frozen=True, slots=True)
class AgentPaymentConfig:
    network_deployment: Path
    price_atomic: str
    recipient: str
    facilitator_url: str


@dataclass(frozen=True, slots=True)
class AgentRegistrationConfig:
    document_path: Path
    public_url: str
    owner_key_env: str


@dataclass(frozen=True, slots=True)
class AdvertisedListing:
    amount: str
    asset: str
    authority: str


def _parse_executor(skill_data: dict, skill_index: int) -> ExecutorConfig:
    field = f"skills[{skill_index}].executor"
    executor_data = _require_object(skill_data, "executor")
    executor_type = _require_string(executor_data, "type")

    if executor_type == "ollama":
        return ExecutorConfig(
            executor_type=executor_type,
            model=_require_string(executor_data, "model"),
            host=_require_http_url(
                _require_string(executor_data, "host"),
                f"{field}.host",
            ),
            system_prompt=_require_string(executor_data, "systemPrompt"),
        )

    if executor_type == "deterministic":
        latency_ms = int(executor_data["latencyMs"])
        retention_ratio = float(executor_data["retentionRatio"])
        if latency_ms < 0:
            raise ValueError(f"{field}.latencyMs must be non-negative")
        if not 0 < retention_ratio <= 1:
            raise ValueError(f"{field}.retentionRatio must be in (0, 1]")
        return ExecutorConfig(
            executor_type=executor_type,
            latency_ms=latency_ms,
            retention_ratio=retention_ratio,
        )

    raise ValueError(f"unsupported executor type: {executor_type}")


def _parse_skills(data: dict) -> tuple[SkillConfig, ...]:
    raw_skills = data.get("skills")
    if not isinstance(raw_skills, list) or not raw_skills:
        raise ValueError("agent configuration field 'skills' must be a non-empty list")

    skills: list[SkillConfig] = []
    for index, skill_data in enumerate(raw_skills):
        if not isinstance(skill_data, dict):
            raise ValueError(f"agent skills[{index}] must be an object")

        raw_tags = skill_data.get("tags")
        if not isinstance(raw_tags, list) or not raw_tags or not all(
            isinstance(tag, str) and tag.strip() for tag in raw_tags
        ):
            raise ValueError(
                f"agent skills[{index}].tags must be a non-empty string list"
            )

        skills.append(
            SkillConfig(
                skill_id=_require_string(skill_data, "id"),
                name=_require_string(skill_data, "name"),
                description=_require_string(skill_data, "description"),
                tags=tuple(raw_tags),
                executor=_parse_executor(skill_data, index),
            )
        )

    skill_ids = [skill.skill_id for skill in skills]
    if len(skill_ids) != len(set(skill_ids)):
        raise ValueError("agent skill IDs must be unique")
    return tuple(skills)


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Everything an operator supplies to start and register one agent."""

    source_path: Path
    name: str
    description: str
    version: str
    host: str
    port: int
    base_url: str
    skills: tuple[SkillConfig, ...]
    payment: AgentPaymentConfig | None
    registration: AgentRegistrationConfig | None
    test_listing: AdvertisedListing | None

    @property
    def agent_card_url(self) -> str:
        return f"{self.base_url}/.well-known/agent-card.json"

    @property
    def skill_ids(self) -> tuple[str, ...]:
        return tuple(skill.skill_id for skill in self.skills)

    @classmethod
    def from_path(cls, path: Path | str) -> "AgentConfig":
        source_path = Path(path).resolve()
        data = json.loads(source_path.read_text(encoding="utf-8"))
        server = _require_object(data, "server")

        port = int(server["port"])
        if not 1 <= port <= 65535:
            raise ValueError("agent server port must be between 1 and 65535")

        payment = None
        payment_data = data.get("payment")
        if payment_data is not None:
            if not isinstance(payment_data, dict):
                raise ValueError("agent payment configuration must be an object")
            price_atomic = _require_string(payment_data, "priceAtomic")
            if not price_atomic.isdigit() or int(price_atomic) <= 0:
                raise ValueError("agent payment priceAtomic must be a positive integer")
            payment = AgentPaymentConfig(
                network_deployment=_resolve_path(
                    source_path,
                    _require_string(payment_data, "networkDeployment"),
                ),
                price_atomic=price_atomic,
                recipient=Web3.to_checksum_address(
                    _require_string(payment_data, "recipient")
                ),
                facilitator_url=_require_http_url(
                    _require_string(payment_data, "facilitatorUrl"),
                    "payment.facilitatorUrl",
                ),
            )

        registration = None
        registration_data = data.get("registration")
        if registration_data is not None:
            if not isinstance(registration_data, dict):
                raise ValueError("agent registration configuration must be an object")
            registration = AgentRegistrationConfig(
                document_path=_resolve_path(
                    source_path,
                    _require_string(registration_data, "documentPath"),
                ),
                public_url=_require_http_url(
                    _require_string(registration_data, "publicUrl"),
                    "registration.publicUrl",
                ),
                owner_key_env=_require_string(registration_data, "ownerKeyEnv"),
            )

        if (payment is None) != (registration is None):
            raise ValueError(
                "a paid agent must also declare registration, and vice versa"
            )

        test_listing = None
        listing_data = data.get("testListing")
        if listing_data is not None:
            if payment is not None:
                raise ValueError("paid agents derive advertised price from payment config")
            if not isinstance(listing_data, dict):
                raise ValueError("testListing must be an object")
            test_listing = AdvertisedListing(
                amount=_require_string(listing_data, "amount"),
                asset=_require_string(listing_data, "asset"),
                authority="controlled-test-fixture",
            )

        return cls(
            source_path=source_path,
            name=_require_string(data, "name"),
            description=_require_string(data, "description"),
            version=str(data.get("version", "0.1.0")),
            host=_require_string(server, "host"),
            port=port,
            base_url=_require_http_url(
                _require_string(server, "baseUrl"), "server.baseUrl"
            ),
            skills=_parse_skills(data),
            payment=payment,
            registration=registration,
            test_listing=test_listing,
        )
