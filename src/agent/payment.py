"""Seller-side x402 policy for an A2A agent."""

from __future__ import annotations

from dataclasses import dataclass

from x402 import x402ResourceServer
from x402.http import FacilitatorConfig as HTTPFacilitatorConfig
from x402.http import HTTPFacilitatorClient, PaymentOption
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import register_exact_evm_server
from x402.schemas import AssetAmount

from agent.config import AgentPaymentConfig
from x402_support.network import PaymentNetwork


@dataclass(slots=True)
class AgentPaymentGate:
    """Payment middleware dependencies owned by one agent server."""

    resource_server: x402ResourceServer
    paid_routes: dict[str, RouteConfig]
    facilitator_client: HTTPFacilitatorClient

    async def close(self) -> None:
        await self.facilitator_client.aclose()


def build_payment_gate(
    network: PaymentNetwork,
    policy: AgentPaymentConfig,
) -> AgentPaymentGate:
    """Protect the A2A JSON-RPC route using this agent's own price policy."""

    facilitator_client = HTTPFacilitatorClient(
        HTTPFacilitatorConfig(url=policy.facilitator_url)
    )
    resource_server = x402ResourceServer(facilitator_client)
    register_exact_evm_server(resource_server, networks=network.network)

    payment_asset = AssetAmount(
        amount=policy.price_atomic,
        asset=network.asset,
        extra={
            "name": network.asset_name,
            "version": network.asset_version,
            "assetTransferMethod": "eip3009",
        },
    )
    paid_routes = {
        "POST /": RouteConfig(
            accepts=PaymentOption(
                scheme="exact",
                network=network.network,
                price=payment_asset,
                pay_to=policy.recipient,
                max_timeout_seconds=60,
            ),
            description="One paid A2A summarization invocation",
            mime_type="application/json",
        )
    }
    return AgentPaymentGate(
        resource_server=resource_server,
        paid_routes=paid_routes,
        facilitator_client=facilitator_client,
    )
