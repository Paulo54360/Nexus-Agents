"""Context window optimization (sliding window) to reduce LLM token consumption."""

from __future__ import annotations

from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage

DEFAULT_MAX_MESSAGES = 14
OLD_TOOL_OUTPUT_CHAR_CAP = 1200


def trim_conversation(
    messages: list[AnyMessage],
    max_messages: int = DEFAULT_MAX_MESSAGES,
) -> list[AnyMessage]:
    """Keep a valid recent window starting on a HumanMessage and compact stale tool outputs.

    Prevents orphaned ToolMessages (which cause 400 errors on Mistral/Groq/Gemini)
    while cutting token usage by 3-4x on long Discord threads.
    """
    if not messages:
        return []

    start = max(0, len(messages) - max_messages)
    # Advance to the first HumanMessage so we never split an AI tool_call from its ToolMessage
    while start < len(messages) and not isinstance(messages[start], HumanMessage):
        start += 1

    window = messages[start:] if start < len(messages) else messages[-4:]

    # Compact oversized ToolMessages from earlier turns (keep the last 4 messages untouched)
    recent_cutoff = max(0, len(window) - 4)
    compacted: list[AnyMessage] = []
    for idx, msg in enumerate(window):
        if (
            idx < recent_cutoff
            and isinstance(msg, ToolMessage)
            and isinstance(msg.content, str)
            and len(msg.content) > OLD_TOOL_OUTPUT_CHAR_CAP
        ):
            compacted.append(
                msg.model_copy(
                    update={
                        "content": (
                            msg.content[:OLD_TOOL_OUTPUT_CHAR_CAP]
                            + "\n...[sortie d'outil ancienne tronquée pour économiser les tokens]"
                        )
                    }
                )
            )
        else:
            compacted.append(msg)
    return compacted
