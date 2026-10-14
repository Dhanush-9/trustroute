"""Controlled and LLM-backed A2A executors."""

import asyncio
import time

import httpx
from a2a.helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue

from agent.skill_routing import SKILL_METADATA_KEY


class SkillDispatcher(AgentExecutor):
    """Delegate an A2A request to the explicitly selected skill executor."""

    def __init__(self, executors: dict[str, AgentExecutor]) -> None:
        if not executors:
            raise ValueError("at least one skill executor is required")
        self.executors = executors

    def _selected_executor(self, context: RequestContext) -> AgentExecutor:
        skill_id = context.metadata.get(SKILL_METADATA_KEY)
        if not isinstance(skill_id, str) or skill_id not in self.executors:
            # The outer middleware should make this unreachable. Keeping the
            # check here prevents accidental implicit routing in other servers.
            raise ValueError("request does not select a configured skill")
        return self.executors[skill_id]

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        await self._selected_executor(context).execute(context, event_queue)

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        await self._selected_executor(context).cancel(context, event_queue)


class DeterministicSummarizer(AgentExecutor):
    """Controlled test agent with known delay and sentence retention."""

    def __init__(
        self,
        *,
        agent_name: str,
        latency_ms: int,
        retention_ratio: float,
    ) -> None:
        if latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")

        if not 0 < retention_ratio <= 1:
            raise ValueError("retention_ratio must be in (0, 1]")

        self.agent_name = agent_name
        self.latency_ms = latency_ms
        self.retention_ratio = retention_ratio

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        source = context.get_user_input()

        started = time.perf_counter()

        # Controlled delay.
        await asyncio.sleep(self.latency_ms / 1000)

        # Explicit steps keep the deterministic behavior easy to inspect.
        parts = source.split(".")
        sentences = []

        for part in parts:
            part = part.strip()

            if part:
                sentences.append(part)

        # Retention is controlled behavior, not a semantic quality measurement.
        keep = round(len(sentences) * self.retention_ratio)

        if keep < 1 and len(sentences) > 0:
            keep = 1

        summary = ". ".join(sentences[:keep])

        if summary:
            summary += "."

        elapsed_ms = round((time.perf_counter() - started) * 1000)

        # Responses retain A2A correlation identifiers from the request context.
        await event_queue.enqueue_event(
            new_text_message(
                f"[{self.agent_name} | {elapsed_ms}ms] {summary}",
                context_id=context.context_id,
                task_id=context.task_id,
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancellation is not supported in the baseline")


class OllamaTextExecutor(AgentExecutor):
    """Run one configured text skill through a local Ollama server."""

    def __init__(
        self,
        *,
        agent_name: str,
        skill_id: str,
        model: str,
        host: str,
        system_prompt: str,
    ) -> None:
        self.agent_name = agent_name
        self.skill_id = skill_id
        self.model = model
        self.host = host.rstrip("/")
        self.system_prompt = system_prompt

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        source = context.get_user_input()

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=120, trust_env=False) as http:
                # A non-streaming response keeps the A2A baseline easy to follow.
                response = await http.post(
                    f"{self.host}/api/chat",
                    json={
                        "model": self.model,
                        "stream": False,
                        "messages": [
                            {
                                "role": "system",
                                "content": self.system_prompt,
                            },
                            {"role": "user", "content": source},
                        ],
                    },
                )
                response.raise_for_status()

                data = response.json()

                result = data["message"]["content"].strip()

                print(f"\n--- Ollama metrics: {self.skill_id} ---")
                print(f"Model:        {self.model}")
                print(f"Model load:   {data.get('load_duration', 0) / 1e9:.3f} s")
                print(f"Prompt eval:  {data.get('prompt_eval_duration', 0) / 1e9:.3f} s")
                print(f"Prompt tokens:{data.get('prompt_eval_count', 0)}")
                print(f"Generation:   {data.get('eval_duration', 0) / 1e9:.3f} s")
                print(f"Output tokens:{data.get('eval_count', 0)}")
                print(f"Total Ollama: {data.get('total_duration', 0) / 1e9:.3f} s")
                print("----------------------\n")

        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            result = f"error: could not reach local model ({error})"

        elapsed_ms = round((time.perf_counter() - started) * 1000)

        # The model implementation is hidden behind the same A2A response shape.
        await event_queue.enqueue_event(
            new_text_message(
                f"[{self.agent_name} | {self.skill_id} | {elapsed_ms}ms] {result}",
                context_id=context.context_id,
                task_id=context.task_id,
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancellation is not supported in the baseline")
