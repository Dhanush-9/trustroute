"""Build the HTTP application for an A2A service agent."""

from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard
from starlette.applications import Starlette


def build_app(
    card: AgentCard,
    executor: AgentExecutor,
) -> Starlette:
    # The handler converts A2A requests into RequestContext objects for the
    # executor. The in-memory store is sufficient for this local baseline.
    handler = DefaultRequestHandler(
        agent_executor = executor,
        task_store = InMemoryTaskStore(),
        agent_card = card,
    )

    # The SDK supplies both the well-known AgentCard route and JSON-RPC route.
    routes = [
        *create_agent_card_routes(agent_card = card),
        *create_jsonrpc_routes(request_handler = handler, rpc_url="/"),
    ]
    
    return Starlette(routes = routes)
