"""Unit tests for HITL security policy, mock tool registry, and sliding-window memory."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from nexus.graph.hitl import apply_hitl_policy, requires_approval
from nexus.graph.memory import trim_conversation
from nexus.mcp.registry import get_mock_tools_by_domain


@pytest.mark.parametrize(
    ("tool_name", "expected"),
    [
        # Autonomous actions (no approval required)
        ("gmail_list_unread", False),
        ("gmail_apply_label", False),
        ("gmail_create_draft", False),
        ("calendar_list_events", False),
        ("list-events", False),
        ("notion_list_tasks", False),
        ("notion_create_task", False),
        # High-impact actions (HITL approval required — supports underscore & hyphen MCP names)
        ("gmail_send_email", True),
        ("gmail_reply_email", True),
        ("gmail_delete_email", True),
        ("calendar_create_event", True),
        ("create-event", True),
        ("update-event", True),
        ("delete-event", True),
        ("discord_post_message", True),
    ],
)
def test_hitl_policy_classification(tool_name: str, expected: bool) -> None:
    assert requires_approval(tool_name) is expected


def test_apply_hitl_policy_marks_critical_tools() -> None:
    mock_tools = get_mock_tools_by_domain()
    protected_gmail = apply_hitl_policy(mock_tools["gmail"])
    by_name = {t.name: t for t in protected_gmail}

    assert "[HITL:" in by_name["gmail_send_email"].description
    assert "[HITL:" in by_name["gmail_delete_email"].description
    assert "[HITL:" not in by_name["gmail_list_unread"].description
    assert "[HITL:" not in by_name["gmail_create_draft"].description


def test_trim_conversation_starts_on_human_and_compacts_old_tools() -> None:
    msgs = [
        HumanMessage(content="turn 1"),
        AIMessage(content="calling tool"),
        ToolMessage(content="x" * 5000, tool_call_id="call_1"),
        AIMessage(content="answer 1"),
        HumanMessage(content="turn 2"),
        AIMessage(content="answer 2"),
        HumanMessage(content="turn 3"),
        ToolMessage(content="y" * 5000, tool_call_id="call_2"),
        AIMessage(content="answer 3"),
    ]
    trimmed = trim_conversation(msgs, max_messages=8)

    assert isinstance(trimmed[0], HumanMessage)
    # Earlier tool output is compacted while latest messages stay intact
    tool_msgs = [m for m in trimmed if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert len(tool_msgs[0].content) == 5000
