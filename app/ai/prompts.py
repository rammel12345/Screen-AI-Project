"""System prompts and prompt construction."""
from __future__ import annotations

from app.models import ChatMessage, Screenshot

COMMON_RULES = (
    "You run fully locally. The screen text was extracted by OCR and may contain "
    "recognition mistakes. Clearly separate what is recognized text from your own "
    "assumptions. If the text is incomplete or ambiguous, say so and ask a clarifying "
    "question. Never claim to have seen files or content that were not provided. "
    "You cannot execute code or commands; only suggest them. Use Markdown, and put code "
    "in fenced code blocks."
)

SYSTEM_PROMPTS = {
    "explain": (
        "You are 'Explain Screen', an assistant that explains on-screen content in simple "
        "language. Explain error messages, summarize documents, explain instructions and "
        "workflows, and clarify technical terms. Point out missing or ambiguous context. "
        + COMMON_RULES
    ),
    "coding": (
        "You are 'Coding Helper'. Help the user understand programming content from the "
        "screen: explain code (line by line when asked), variables, parameters, functions "
        "and return values; diagnose compiler, terminal and application errors; suggest "
        "corrections with short examples and explain why they work. Do not claim to have "
        "inspected files that were not provided. " + COMMON_RULES
    ),
    "general": (
        "You are 'General Assistant'. Answer questions about the selected screen content "
        "and help generally. Follow the user's prompt, treat the screenshots in capture "
        "order, avoid unsupported claims, and ask clarifying questions if the OCR text "
        "looks incomplete. " + COMMON_RULES
    ),
}

MODE_LABELS = {"explain": "Explain Screen", "coding": "Coding Helper", "general": "General Assistant"}

DEFAULT_PROMPTS = {
    "explain": "Explain what is on my screen.",
    "coding": "Explain this code or error and how to fix it.",
    "general": "Help me with what is on my screen.",
}


def system_prompt(mode: str) -> str:
    return SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["general"])


def build_screen_context(shots: list[Screenshot], max_chars: int | None = None) -> str:
    """Format selected screenshots' (possibly user-edited) text in capture order."""
    parts = []
    for i, s in enumerate(shots, 1):
        body = s.text.strip() or "(no text recognized)"
        parts.append(f"--- Screenshot {i} (captured {s.timestamp:%H:%M:%S}) ---\n{body}")
    ctx = "\n\n".join(parts)
    if max_chars and len(ctx) > max_chars:
        ctx = ctx[:max_chars] + "\n[... truncated to fit context length ...]"
    return ctx


def build_initial_messages(mode: str, user_prompt: str, shots: list[Screenshot],
                           context_length: int = 4096, images: list[str] | None = None,
                           include_text: bool = True) -> list[ChatMessage]:
    """Reserve ~half the context window for screen text (≈3 chars/token)."""
    user_prompt = user_prompt.strip() or DEFAULT_PROMPTS.get(mode, "")
    max_chars = max(500, int(context_length * 3 * 0.5))
    content = user_prompt
    if include_text:
        content = (f"Screen content (OCR text):\n{build_screen_context(shots, max_chars)}\n\n"
                   f"User request: {user_prompt}")
    elif images:
        content = f"{user_prompt}\n(The attached screenshots are in capture order.)"
    return [
        ChatMessage("system", system_prompt(mode)),
        ChatMessage("user", content, images=images),
    ]


def build_followup(history: list[ChatMessage], question: str) -> list[ChatMessage]:
    return history + [ChatMessage("user", question.strip())]


def trim_history(history: list[ChatMessage], context_length: int) -> list[ChatMessage]:
    """Keep system + first user message (screen context) and as many recent turns as fit."""
    budget = int(context_length * 3 * 0.8)
    if sum(len(m.content) for m in history) <= budget:
        return history
    head, rest = history[:2], history[2:]
    kept: list[ChatMessage] = []
    used = sum(len(m.content) for m in head)
    for m in reversed(rest):
        if used + len(m.content) > budget and kept:
            break
        kept.append(m)
        used += len(m.content)
    return head + list(reversed(kept))
