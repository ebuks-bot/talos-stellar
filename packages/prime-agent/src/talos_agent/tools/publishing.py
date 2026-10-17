"""Publishing tools — unified multi-channel content publishing via adapter registry."""

from __future__ import annotations

import asyncio
import functools
from typing import TYPE_CHECKING, Any, Callable

from rich.console import Console

from talos_agent.tools.registry import tool

if TYPE_CHECKING:
    from talos_agent.adapters.registry import AdapterRegistry

console = Console()

# Injected by registry.build_all_tools
_adapter_registry: AdapterRegistry = None  # type: ignore[assignment]

# Default timeout in seconds; overridden at runtime by the
# ``publish_timeout_seconds`` setting (env ``TALOS_PUBLISH_TIMEOUT``).
# Kept for backward compatibility with tests that import the module directly.
_DEFAULT_TIMEOUT = 90

# Resolved at build_all_tools() time from Settings.publish_timeout_seconds.
_publish_timeout: float = _DEFAULT_TIMEOUT


def set_publish_timeout(timeout: float) -> None:
    """Set the publishing tool timeout, validated via http.validate_tool_timeout."""
    from talos_agent.http import validate_tool_timeout

    global _publish_timeout
    _publish_timeout = validate_tool_timeout(timeout)


def _publish_safe(fn: Callable) -> Callable:
    """Wrap a publishing tool with timeout and structured error handling."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> dict:
        if _adapter_registry is None:
            return {"error": "Adapter registry not initialized"}
        timeout = _publish_timeout
        try:
            return await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)
        except asyncio.TimeoutError:
            return {"error": f"Publishing action timed out after {timeout:g}s"}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    return wrapper


@tool(
    "publish_content",
    "Publish content to a social channel. Call get_publishing_channels first to see available channels and their character limits.",
)
@_publish_safe
async def publish_content(
    content: str, channel: str = "X", operation_id: str | None = None
) -> dict:
    adapter = _adapter_registry.get(channel)
    if not adapter:
        return {
            "error": f"Channel '{channel}' not available.",
            "available_channels": _adapter_registry.available_channels(),
        }
    valid, error = adapter.validate_content(content)
    if not valid:
        return {"error": error}
    result = await adapter.post(content, operation_id=operation_id)
    return result.to_dict()


@tool(
    "reply_on_channel",
    "Reply to a post on a social channel. Requires channel name, target post URL, and reply content.",
)
@_publish_safe
async def reply_on_channel(
    channel: str,
    target_url: str,
    content: str,
    operation_id: str | None = None,
) -> dict:
    adapter = _adapter_registry.get(channel)
    if not adapter:
        return {"error": f"Channel '{channel}' not available"}
    caps = adapter.get_capabilities()
    if not caps.supports_replies:
        return {"error": f"Channel '{channel}' does not support replies"}
    valid, error = adapter.validate_content(content)
    if not valid:
        return {"error": error}
    result = await adapter.reply(target_url, content, operation_id=operation_id)
    return result.to_dict()


@tool(
    "get_channel_mentions",
    "Get recent mentions or notifications from a social channel.",
)
@_publish_safe
async def get_channel_mentions(channel: str = "X") -> dict:
    adapter = _adapter_registry.get(channel)
    if not adapter:
        return {"error": f"Channel '{channel}' not available"}
    mentions = await adapter.get_mentions()
    return {"channel": channel, "mentions": mentions}


@tool(
    "search_channel",
    "Search for posts on a social channel by keyword query.",
)
@_publish_safe
async def search_channel(query: str, channel: str = "X") -> dict:
    adapter = _adapter_registry.get(channel)
    if not adapter:
        return {"error": f"Channel '{channel}' not available"}
    caps = adapter.get_capabilities()
    if not caps.supports_search:
        return {"error": f"Channel '{channel}' does not support search"}
    results = await adapter.search(query)
    return {"channel": channel, "query": query, "results": results}


@tool(
    "get_publishing_channels",
    "Get all available social publishing channels and their capabilities (character limits, supported features). Call this before composing content.",
)
async def get_publishing_channels() -> dict:
    if _adapter_registry is None:
        return {"error": "Adapter registry not initialized"}
    return {
        "available": _adapter_registry.available_channels(),
        "channels": _adapter_registry.capabilities(),
    }
