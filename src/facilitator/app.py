"""Expose the x402 facilitator interface over local HTTP."""

from __future__ import annotations

import os

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from web3 import Web3
from x402 import x402Facilitator
from x402.mechanisms.evm import FacilitatorWeb3Signer
from x402.mechanisms.evm.exact import register_exact_evm_facilitator
from x402.schemas import parse_payment_payload, parse_payment_requirements

from facilitator.config import LocalFacilitatorConfig
from x402_support.network import PaymentNetwork


def _json_model(model) -> dict:
    return model.model_dump(by_alias=True, exclude_none=True)


def build_facilitator_app(
    config: LocalFacilitatorConfig,
    network: PaymentNetwork,
) -> Starlette:
    """Create the local HTTP boundary around the official SDK facilitator."""

    private_key = os.environ.get("TRUSTROUTE_FACILITATOR_PRIVATE_KEY")
    if not private_key:
        raise RuntimeError("TRUSTROUTE_FACILITATOR_PRIVATE_KEY is required")

    signer = FacilitatorWeb3Signer(
        private_key=private_key,
        rpc_url=network.rpc_url,
        confirmation_timeout_seconds=15,
    )
    if signer.address.lower() != config.expected_signer.lower():
        raise ValueError("facilitator key does not match expectedSigner")

    web3 = Web3(Web3.HTTPProvider(network.rpc_url))
    if not web3.is_connected() or web3.eth.chain_id != network.chain_id:
        raise ConnectionError("cannot connect to the expected payment network")
    if web3.eth.get_balance(config.expected_signer) == 0:
        raise RuntimeError("facilitator has no native gas balance")

    facilitator = x402Facilitator()
    register_exact_evm_facilitator(
        facilitator,
        signer,
        networks=network.network,
    )

    async def supported(_: Request) -> JSONResponse:
        return JSONResponse(_json_model(facilitator.get_supported()))

    async def verify(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            version = int(body["x402Version"])
            payload = parse_payment_payload(body["paymentPayload"])
            requirements = parse_payment_requirements(
                version, body["paymentRequirements"]
            )
            result = await facilitator.verify(payload, requirements)
            print(
                "Facilitator verify: "
                f"{'valid' if result.is_valid else result.invalid_reason}"
            )
            return JSONResponse(_json_model(result))
        except (KeyError, TypeError, ValueError) as error:
            return JSONResponse({"error": str(error)}, status_code=400)

    async def settle(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            version = int(body["x402Version"])
            payload = parse_payment_payload(body["paymentPayload"])
            requirements = parse_payment_requirements(
                version, body["paymentRequirements"]
            )
            result = await facilitator.settle(payload, requirements)
            print(
                "Facilitator settle: "
                f"{'successful' if result.success else result.error_reason} "
                f"{result.transaction}"
            )
            return JSONResponse(_json_model(result))
        except (KeyError, TypeError, ValueError) as error:
            return JSONResponse({"error": str(error)}, status_code=400)

    return Starlette(
        routes=[
            Route("/supported", supported, methods=["GET"]),
            Route("/verify", verify, methods=["POST"]),
            Route("/settle", settle, methods=["POST"]),
        ]
    )
