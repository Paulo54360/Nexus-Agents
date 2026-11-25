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
        AIMessage(content="", tool_calls=[{"id": "call_1", "name": "search", "args": {}}]),
        ToolMessage(content="x" * 5000, tool_call_id="call_1"),
        AIMessage(content="answer 1"),
        HumanMessage(content="turn 2"),
        AIMessage(content="answer 2"),
        HumanMessage(content="turn 3"),
        AIMessage(content="", tool_calls=[{"id": "call_2", "name": "search", "args": {}}]),
        ToolMessage(content="y" * 5000, tool_call_id="call_2"),
        AIMessage(content="answer 3"),
    ]
    trimmed = trim_conversation(msgs, max_messages=8)

    assert isinstance(trimmed[0], HumanMessage)
    tool_msgs = [m for m in trimmed if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert len(tool_msgs[0].content) == 5000


def test_trim_conversation_long_single_turn_never_orphans_tool_messages() -> None:
    """Regression test: a single turn with 12+ tool calls must never produce orphaned ToolMessages."""
    msgs: list = [HumanMessage(content="Analyse tous mes emails et propose des labels")]
    for i in range(12):
        call_id = f"call_{i}"
        msgs.append(
            AIMessage(content="", tool_calls=[{"id": call_id, "name": "search_emails", "args": {}}])
        )
        msgs.append(ToolMessage(content=f"email batch {i}", tool_call_id=call_id))

    trimmed = trim_conversation(msgs, max_messages=10)

    # First message must stay the user's HumanMessage
    assert isinstance(trimmed[0], HumanMessage)
    # Never starts with ToolMessage, and every ToolMessage follows its declaring AIMessage
    seen_ids: set[str] = set()
    for msg in trimmed:
        if isinstance(msg, AIMessage):
            seen_ids = {tc["id"] for tc in (msg.tool_calls or [])}
        elif isinstance(msg, ToolMessage):
            assert msg.tool_call_id in seen_ids
        else:
            seen_ids = set()
