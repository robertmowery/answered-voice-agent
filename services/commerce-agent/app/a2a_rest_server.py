"""Serve the commerce agent over A2A 1.0 (HTTP+JSON binding) for CX Agent Studio's A2A tool.

CX Agent Studio appends /message:send to the interface URL in the agent card, so
the card's URL is this service's base URL plus /v1, where the REST routes live.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import os

import uvicorn
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.rest_routes import create_rest_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.agent import root_agent

PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8080")


def card() -> AgentCard:
    return AgentCard(
        name="brightwater_commerce",
        description=root_agent.description,
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(url=f"{PUBLIC_URL}/v1", protocol_binding="HTTP+JSON", protocol_version="1.0")
        ],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[
            AgentSkill(
                id="order_parts_and_plans",
                name="Order parts and plans",
                description="Filters, UV lamps, humidifier pads, water filter cartridges and maintenance plans.",
                tags=["commerce", "ucp"],
                examples=["I need two 16 by 25 by 4 furnace filters", "Sign me up for the maintenance plan"],
            )
        ],
    )


def runner() -> Runner:
    return Runner(
        app_name="brightwater_commerce",
        agent=root_agent,
        session_service=InMemorySessionService(),
        artifact_service=InMemoryArtifactService(),
        memory_service=InMemoryMemoryService(),
    )


async def health(_request: object) -> JSONResponse:
    return JSONResponse({"status": "ok"})


AGENT_CARD = card()
handler = DefaultRequestHandler(
    agent_executor=A2aAgentExecutor(runner=runner()), task_store=InMemoryTaskStore(), agent_card=AGENT_CARD
)
app = Starlette(
    routes=[
        Route("/health", health),
        *create_agent_card_routes(AGENT_CARD),
        *create_rest_routes(handler, path_prefix="/v1"),
    ]
)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
