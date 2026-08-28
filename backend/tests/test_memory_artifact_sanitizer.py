"""Tests for keeping thread-scoped artifact capabilities out of memory."""

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.artifact_sanitizer import (
    sanitize_memory_artifact_references,
    sanitize_memory_messages,
)


def test_sanitizer_removes_paths_and_signed_links_recursively():
    value = {
        "summary": "Report: /mnt/user-data/outputs/report.md.",
        "facts": ["Download https://mmkb.example/api/deerflow/artifacts/signed-token"],
    }

    result = sanitize_memory_artifact_references(value)

    assert "/mnt/user-data/outputs/" not in repr(result)
    assert "/api/deerflow/artifacts/" not in repr(result)
    assert "report.md" in result["summary"]
    assert "下载链接已省略" in result["facts"][0]
    assert value["summary"].startswith("Report: /mnt/user-data/outputs/")


def test_message_sanitizer_preserves_message_types_without_mutating_inputs():
    messages = [
        HumanMessage(content="please inspect"),
        AIMessage(
            content=[
                {"type": "text", "text": "/mnt/user-data/outputs/answer.md"},
                {"type": "text", "text": "/api/agent/artifacts/token"},
            ]
        ),
    ]

    result = sanitize_memory_messages(messages)

    assert isinstance(result[0], HumanMessage)
    assert isinstance(result[1], AIMessage)
    assert "/mnt/user-data/outputs/" not in repr(result)
    assert "/api/agent/artifacts/" not in repr(result)
    assert "/mnt/user-data/outputs/answer.md" in repr(messages)
