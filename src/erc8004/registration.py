from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from erc8004.identity import AgentIdentity


REGISTRATION_TYPE = "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"

# Custom Error for invalid registration documents

class RegistrationError(ValueError):
    pass


# Data Classes used after parsing registration.json

@dataclass(frozen=True, slots=True)
class RegistrationService:
    
    name: str
    endpoint: str
    version: str

@dataclass(frozen=True, slots=True)
class RegistrationDocument:

    name: str
    description: str
    services: tuple[RegistrationService, ...]
    x402_support: bool

    @property
    def a2a_service(self) -> RegistrationService:
        # Parser guarantees that exactly one A2A service exists
        return next(
            service
            for service in self.services
            if service.name == "A2A"
        )


# Helper validation functions

def require_string(data: dict[str, Any], field: str) -> str:
    value = data.get(field)

    if not isinstance(value, str) or not value.strip():
        raise RegistrationError(
            f"registration field '{field}' must be a string"
        )
    
    return value


def require_http_url(value: str, field: str) -> str:
    parsed = urlsplit(value)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RegistrationError(
            f"registration field '{field}' must be an HTTP URL"
        )
    
    return value


# Validate and Parse registration.json

def parse_registration_document(
    data: object,
    *,
    expected_identity: AgentIdentity,
) -> RegistrationDocument:

    if not isinstance(data, dict):
        raise RegistrationError(
            "registration document must be a JSON object"
        )
            
    if data.get("type") != REGISTRATION_TYPE:
        raise RegistrationError(
            "unsupported ERC-8004 registration type"
        )

    if data.get("active") is not True:
        raise RegistrationError(
            "registration is not active"
        )

    name = require_string(data, "name")
    description = require_string(data, "description")

    x402_support = data.get("x402Support")
    if not isinstance(x402_support, bool):
        raise RegistrationError(
            "registration field 'x402Support' must be boolean"
        )

    registrations = data.get("registrations")
    if not isinstance(registrations, list):
        raise RegistrationError(
            "registration field 'registrations' must be a list"
        )

    expected_registry = expected_identity.registry.lower()

    identity_matches = any(
        isinstance(item, dict)
        and item.get("agentId") == expected_identity.agent_id
        and isinstance(item.get("agentRegistry"), str)
        and item["agentRegistry"].lower() == expected_registry
        for item in registrations
    )
    if not identity_matches:
        raise RegistrationError(
            "registration document does not match requested identity"
        )

    # Parse and validate advertised services

    raw_services = data.get("services")
    if not isinstance(raw_services, list):
        raise RegistrationError(
            "registration field 'services' must be a list"
            )

    services: list[RegistrationService] = []

    for index, item in enumerate(raw_services):
        if not isinstance(item, dict):
            raise RegistrationError(
                f"services[{index}] must be an object"
            )

        service = RegistrationService(
            name = require_string(item, "name"),
            endpoint = require_http_url(
                require_string(item, "endpoint"),
                f"services[{index}].endpoint",
            ),
            version = require_string(item, "version"),
        )

        services.append(service)

    # Require exactly one A2A endpoint

    a2a_services = [
        service 
        for service in services
        if service.name == "A2A"
    ]

    if len(a2a_services) != 1:
        raise RegistrationError(
            "registration must advertise exactly one A2A service"
        )

    # Return the validated information as a Python object
    return RegistrationDocument(
        name=name,
        description=description,
        services=tuple(services),
        x402_support=x402_support,
    )
