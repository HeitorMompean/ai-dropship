"""CrewAI crew configuration and LLM setup."""

import logging
from typing import Any, Dict, List, Optional

from langchain_ollama import ChatOllama

from app.config import settings
from app.agents.memory import conversation_memory

logger = logging.getLogger(__name__)


def get_ollama_llm(model=None):
    """Return a ChatOllama instance configured from app settings."""
    return ChatOllama(
        base_url=settings.ollama_base_url,
        model=model or settings.ollama_model,
        temperature=0.7,
    )


def create_agent(role, goal, backstory, tools, allow_delegation=False, verbose=True):
    """Factory - returns None. Agents use tools directly, not CrewAI Agent."""
    logger.info("Agent '%s' registered (tools: %s)", role, len(tools))
    return None  # CrewAI Agent not used - agents call tools directly


def create_task(description, expected_output, agent, context=None):
    """Factory stub."""
    return None


def create_crew(agents, tasks, process=None):
    """Factory stub."""
    return None


def wrap_async_tool(async_func):
    """Wrap an async function into a sync callable for tools."""
    import asyncio

    def sync_wrapper(*args, **kwargs):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, async_func(*args, **kwargs))
                    return future.result()
            return loop.run_until_complete(async_func(*args, **kwargs))
        except RuntimeError:
            return asyncio.run(async_func(*args, **kwargs))

    return sync_wrapper
