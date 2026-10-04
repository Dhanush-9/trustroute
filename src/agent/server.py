"""Build the HTTP application for an A2A service agent."""

import json
from pathlib import Path

from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


def build_app(
    card: AgentCard,
    executor: AgentExecutor,
    *,
    registration_document_path: Path | None = None,
) -> Starlette:
    # The handler converts A2A requests into RequestContext objects for the
    # executor. The in-memory store is sufficient for this local baseline.
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    # The SDK supplies both the well-known AgentCard route and JSON-RPC route.
    routes = [
        *create_agent_card_routes(agent_card=card),
        *create_jsonrpc_routes(request_handler=handler, rpc_url="/"),
    ]

    if registration_document_path is not None:

        async def registration_document(_: Request) -> JSONResponse:
            """Serve the generated off-chain document linked by agentURI."""

            try:
                data = json.loads(
                    registration_document_path.read_text(encoding="utf-8")
                )
            except FileNotFoundError:
                return JSONResponse(
                    {"error": "agent has not been registered yet"},
                    status_code=404,
                )
            except json.JSONDecodeError:
                return JSONResponse(
                    {"error": "registration document is invalid"},
                    status_code=500,
                )
            return JSONResponse(data)

        routes.append(Route("/registration.json", registration_document))

    return Starlette(routes=routes)
