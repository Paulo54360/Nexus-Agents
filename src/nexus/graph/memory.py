"""Context window optimization (sliding window) to reduce LLM token consumption."""

from __future__ import annotations

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

DEFAULT_MAX_MESSAGES = 14
OLD_TOOL_OUTPUT_CHAR_CAP = 1200
RECENT_TOOL_OUTPUT_CHAR_CAP = 12000


def _drop_orphaned_tool_messages(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Ensure every ToolMessage follows an AIMessage that declared its tool_call_id.

    Mistral (code 3230), Gemini, and Groq Harmony all reject requests containing
    a ToolMessage whose corresponding AIMessage tool_call was sliced away.
    """
    cleaned: list[AnyMessage] = []
    active_call_ids: set[str] = set()

    for msg in messages:
        if isinstance(msg, ToolMessage):
            call_id = getattr(msg, "tool_call_id", None)
            if call_id and call_id in active_call_ids:
                cleaned.append(msg)
            continue

        if isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", None) or []
            active_call_ids = {str(tc["id"]) for tc in tool_calls if isinstance(tc, dict) and tc.get("id")}
            cleaned.append(msg)
        else:
            active_call_ids = set()
            cleaned.append(msg)

    return cleaned


def trim_conversation(
    messages: list[AnyMessage],
    max_messages: int = DEFAULT_MAX_MESSAGES,
) -> list[AnyMessage]:
    """Keep a valid recent window starting on a HumanMessage and compact oversized tool outputs.

    Guarantees two invariants across Mistral, Gemini, and Groq:
    1. Never starts on or keeps an orphaned ToolMessage (even during 20+ tool-call single turns).
    2. Caps old tool outputs at 1.2k chars and recent tool outputs at 12k chars to prevent 429 TPM bursts.
    """
    if not messages:
        return []

    if len(messages) <= max_messages:
        window = list(messages)
    else:
        start = len(messages) - max_messages
        # Prefer advancing to a HumanMessage boundary so full turns stay intact
        human_start = start
        while human_start < len(messages) and not isinstance(messages[human_start], HumanMessage):
            human_start += 1

        if human_start < len(messages):
            window = list(messages[human_start:])
        else:
            # Single ongoing turn with > max_messages tool steps: preserve the latest HumanMessage
            # plus the most recent valid AIMessage/ToolMessage tail.
            last_human_idx = next(
                (i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)),
                None,
            )
            tail_start = max(0, len(messages) - max(4, max_messages - 1))
            while tail_start < len(messages) and isinstance(messages[tail_start], ToolMessage):
                tail_start += 1

            if last_human_idx is not None and last_human_idx < tail_start:
                window = [messages[last_human_idx], *messages[tail_start:]]
            else:
                window = list(messages[tail_start:])

    window = _drop_orphaned_tool_messages(window)

    # Compact oversized ToolMessages (older turns aggressively, recent turns safely)
    recent_cutoff = max(0, len(window) - 4)
    compacted: list[AnyMessage] = []
    for idx, msg in enumerate(window):
        if isinstance(msg, ToolMessage) and isinstance(msg.content, str):
            cap = OLD_TOOL_OUTPUT_CHAR_CAP if idx < recent_cutoff else RECENT_TOOL_OUTPUT_CHAR_CAP
            if len(msg.content) > cap:
                compacted.append(
                    msg.model_copy(
                        update={
                            "content": (
                                msg.content[:cap]
                                + "\n...[sortie d'outil tronquée pour économiser les tokens]"
                            )
                        }
                    )
                )
                continue
        compacted.append(msg)
    return compacted
