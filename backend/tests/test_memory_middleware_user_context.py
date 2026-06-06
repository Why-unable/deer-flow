"""Tests for user-scoped memory middleware behavior."""

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.config.memory_config import MemoryConfig


def test_memory_middleware_prefers_runtime_user_id():
    """Memory updates must retain the authenticated user across background work."""
    middleware = MemoryMiddleware(
        agent_name="research-analyst",
        memory_config=MemoryConfig(enabled=True),
    )
    runtime = MagicMock(
        context={
            "thread_id": "thread-1",
            "user_id": "mmkb-workspace-user",
        }
    )
    state = {
        "messages": [
            HumanMessage(content="Remember that I prefer concise answers."),
            AIMessage(content="Understood."),
        ]
    }

    with patch("deerflow.agents.middlewares.memory_middleware.get_memory_queue") as get_queue:
        middleware.after_agent(state, runtime)

    get_queue.return_value.add.assert_called_once()
    assert get_queue.return_value.add.call_args.kwargs["user_id"] == "mmkb-workspace-user"
