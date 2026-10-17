import re

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_response import LlmResponse

_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", flags=re.DOTALL | re.IGNORECASE)
_MOJIBAKE_MARKERS = ("Ã", "â", "ð")


class IncompleteModelOutputError(RuntimeError):
    """Raised when a model response ends before a safe final answer exists."""


def clean_model_text(text: str) -> str:
    """Remove thinking tags and repair common UTF-8/Windows mojibake."""
    cleaned = _THINK_BLOCK.sub("", text)
    lowered = cleaned.lower()

    if "</think>" in lowered:
        closing_tag_end = lowered.rfind("</think>") + len("</think>")
        cleaned = cleaned[closing_tag_end:]

    lowered = cleaned.lower()
    if "<think>" in lowered:
        cleaned = cleaned[: lowered.find("<think>")]

    cleaned = cleaned.strip()
    if not any(marker in cleaned for marker in _MOJIBAKE_MARKERS):
        return cleaned

    try:
        return cleaned.encode("cp1252").decode("utf-8")
    except UnicodeError:
        return cleaned


def sanitize_model_response(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> LlmResponse | None:
    """Strip leaked thinking before ADK stores or forwards model output."""
    del callback_context

    if (
        llm_response.finish_reason
        and "MAX_TOKENS" in str(llm_response.finish_reason).upper()
    ):
        raise IncompleteModelOutputError(
            "Model output reached its token limit before completing"
        )

    if not llm_response.content or not llm_response.content.parts:
        return None

    changed = False
    parts = []
    for part in llm_response.content.parts:
        if part.text is None:
            parts.append(part)
            continue

        cleaned = clean_model_text(part.text)
        changed = changed or cleaned != part.text
        parts.append(part.model_copy(update={"text": cleaned}))

    if not changed:
        return None

    content = llm_response.content.model_copy(update={"parts": parts})
    return llm_response.model_copy(update={"content": content})


def get_local_model() -> LiteLlm:
    return LiteLlm(
        model="ollama_chat/qwen3:4b-instruct",
        think=False,
    )
