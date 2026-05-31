import json
import time

from agent.config import MODEL

from agent.constants import COMPACT_KEEP_RECENT, MAX_TOKENS_COMPACT, TRANSCRIPT_DIR


def estimate_tokens(messages: list) -> int:
    return len(str(messages)) // 4


def micro_compact(messages: list) -> list:
    tool_results = [
        part
        for msg in messages
        if msg["role"] == "user" and isinstance(msg.get("content"), list)
        for part in msg["content"]
        if isinstance(part, dict) and part.get("type") == "tool_result"
    ]
    if len(tool_results) <= COMPACT_KEEP_RECENT:
        return messages
    tool_name_map = {
        block.id: block.name
        for msg in messages
        if msg["role"] == "assistant" and isinstance(msg.get("content"), list)
        for block in msg["content"]
        if hasattr(block, "type") and block.type == "tool_use"
    }
    for result in tool_results[:-COMPACT_KEEP_RECENT]:
        if isinstance(result.get("content"), str) and len(result["content"]) > 100:
            tool_name = tool_name_map.get(result.get("tool_use_id", ""), "unknown")
            result["content"] = f"[Previous: used {tool_name}]"
    return messages


def auto_compact(client, messages: list) -> list:
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(transcript_path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    print(f"[transcript saved: {transcript_path}]")
    conversation_text = json.dumps(messages, default=str)[:80000]
    response = client.messages.create(
        model=MODEL,
        messages=[{"role": "user", "content":
            "Summarize this conversation for continuity. Include: "
            "1) What was accomplished, 2) Current state, 3) Key decisions made. "
            "Be concise but preserve critical details.\n\n" + conversation_text}],
        max_tokens=MAX_TOKENS_COMPACT,
    )
    summary = response.content[0].text
    # Return a single user message (no trailing assistant). Anthropic's
    # messages.create requires the conversation to end with a user message
    # (assistant prefill is a separate, opt-in feature); an assistant "Understood"
    # placeholder here would cause the very next LLM call to 400 with
    # "This model does not support assistant message prefill. The conversation
    # must end with a user message."
    return [
        {"role": "user", "content":
            f"[Conversation compressed. Transcript: {transcript_path}]\n\n"
            f"{summary}\n\n"
            "Continue from where we left off."},
    ]
