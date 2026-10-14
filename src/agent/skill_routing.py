"""Bind an explicitly requested skill to an A2A JSON-RPC invocation."""

from __future__ import annotations

import json

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


SKILL_HEADER = "X-TrustRoute-Skill"
SKILL_HEADER_BYTES = SKILL_HEADER.lower().encode("ascii")
SKILL_METADATA_KEY = "trustroute.skill_id"
SKILL_ROUTING_EXTENSION_URI = (
    "https://trustroute.example/extensions/skill-routing/v1"
)


def _request_skill(payload: object) -> str | None:
    """Read TrustRoute's skill identifier from A2A request metadata."""

    if not isinstance(payload, dict):
        return None
    params = payload.get("params")
    if not isinstance(params, dict):
        return None
    metadata = params.get("metadata")
    if not isinstance(metadata, dict):
        return None
    skill_id = metadata.get(SKILL_METADATA_KEY)
    return skill_id if isinstance(skill_id, str) and skill_id else None


class SkillRoutingMiddleware:
    """Reject ambiguous skill requests before x402 can issue a challenge."""

    def __init__(self, app: ASGIApp, *, skill_ids: tuple[str, ...]) -> None:
        self.app = app
        self.skill_ids = frozenset(skill_ids)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] != "/"
        ):
            await self.app(scope, receive, send)
            return

        body, disconnected = await self._read_body(receive)
        if disconnected:
            return

        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            await self._reject(scope, receive, send, "request body is not valid JSON")
            return

        header_skill = self._header_skill(scope)
        metadata_skill = _request_skill(payload)

        if header_skill is None or metadata_skill is None:
            await self._reject(
                scope,
                receive,
                send,
                f"skill must be supplied in {SKILL_HEADER} and A2A request metadata",
            )
            return
        if header_skill != metadata_skill:
            await self._reject(
                scope,
                receive,
                send,
                "skill header does not match A2A request metadata",
            )
            return
        if header_skill not in self.skill_ids:
            await self._reject(
                scope,
                receive,
                send,
                f"agent does not advertise skill {header_skill!r}",
            )
            return

        replay = self._replay_body(body)
        await self.app(scope, replay, send)

    @staticmethod
    async def _read_body(receive: Receive) -> tuple[bytes, bool]:
        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return b"", True
            if message["type"] != "http.request":
                continue
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                return b"".join(chunks), False

    @staticmethod
    def _header_skill(scope: Scope) -> str | None:
        for name, value in scope["headers"]:
            if name.lower() == SKILL_HEADER_BYTES:
                decoded = value.decode("utf-8").strip()
                return decoded or None
        return None

    @staticmethod
    def _replay_body(body: bytes) -> Receive:
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        return replay

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        reason: str,
    ) -> None:
        response = JSONResponse(
            {"error": "invalid skill selection", "detail": reason},
            status_code=400,
        )
        await response(scope, receive, send)
