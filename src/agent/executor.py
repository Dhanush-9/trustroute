"""Controlled and LLM-backed A2A executors."""

import asyncio
import os
import time

import httpx
from a2a.helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue


class DeterministicSummarizer(AgentExecutor):
    """Controlled test agent with known delay and sentence retention."""

    def __init__( self, *, agent_name: str, latency_ms: int, retention_ratio: float):
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
        event_queue: EventQueue
    ) -> None:

        source = context.get_user_input()

        started = time.perf_counter()

        #sleep to simulate latency
        await asyncio.sleep(self.latency_ms / 1000)

        #separating the texxt into sentences
        parts = source.split(".")

        sentences = []

        for part in parts:
            part = part.strip()

            if part:
                sentences.append(part)

        #decide how many sentences to keep
        keep = round(len(sentences) * self.retention_ratio)

        if keep < 1 and len(sentences) > 0:
            keep = 1

        summary = ". ".join(sentences[:keep])

        if summary:
            summary += "."

        elapsed_ms = round((time.perf_counter() - started) * 1000)

        #how executor talks back
        await event_queue.enqueue_event(
            new_text_message(
                f"[{self.agent_name} | {elapsed_ms}ms] {summary}",
                context_id = context.context_id,
                task_id = context.task_id,
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancellation is not supported in the baseline")


class OllamaSummarizer(AgentExecutor):
    """Real summarization through a locally running Ollama server."""

    def __init__(self, *, agent_name: str):
        self.agent_name = agent_name
        self.model = os.getenv("OLLAMA_MODEL", "llama3.2")
        self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        source = context.get_user_input()
        
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=120, trust_env=False) as http:

                #sending a HTTP POST request
                response = await http.post(
                    f"{self.host}/api/chat",
                    json={
                        "model": self.model,
                        "stream": False,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Summarize the text in short. Return only the summary.",
                            },
                            {"role": "user", "content": source},
                        ],
                    },
                )
                response.raise_for_status()

                data = response.json()

                summary = data["message"]["content"].strip()

                print("\n--- Ollama metrics ---")
                print(f"Model load:   {data.get('load_duration', 0) / 1e9:.3f} s")
                print(f"Prompt eval:  {data.get('prompt_eval_duration', 0) / 1e9:.3f} s")
                print(f"Prompt tokens:{data.get('prompt_eval_count', 0)}")
                print(f"Generation:   {data.get('eval_duration', 0) / 1e9:.3f} s")
                print(f"Output tokens:{data.get('eval_count', 0)}")
                print(f"Total Ollama: {data.get('total_duration', 0) / 1e9:.3f} s")
                print("----------------------\n")

        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            summary = f"error: could not reach local model ({error})"

        elapsed_ms = round((time.perf_counter() - started) * 1000)

        #how executor talks back
        await event_queue.enqueue_event(
            new_text_message(
                f"[{self.agent_name} | {elapsed_ms}ms] {summary}",
                context_id=context.context_id,
                task_id=context.task_id,
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancellation is not supported in the baseline")
