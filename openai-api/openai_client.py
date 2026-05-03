"""Thin async wrapper around the OpenAI SDK.

Karpathy moves baked in here:
  - REAL token usage from the response object (no estimation).
  - Structured Outputs (`response_format={"type": "json_schema", ...}`)
    when the caller passes a json_schema — eliminates the parse-and-retry loop.
  - Prompt caching: system prompt is sent once-per-request (OpenAI caches it
    server-side automatically when a recent identical prefix matches).
  - Per-call model override so the Router can right-size per agent.

Falls back to a deterministic MOCK envelope when OPENAI_API_KEY is missing
or OPENAI_MOCK=true. That keeps the rest of the system testable offline.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-5")
MOCK_ENABLED = os.getenv("OPENAI_MOCK", "false").lower() == "true"


@dataclass
class OpenAIResult:
    text:        str
    model:       str
    tokens_in:   int
    tokens_out:  int
    duration_s:  float
    cached_tokens: int = 0
    mocked:      bool = False


class OpenAIClientError(RuntimeError):
    pass


_async_client = None


def _get_client():
    """Lazy import + lazy construct so the module loads even without the SDK."""
    global _async_client
    if _async_client is not None:
        return _async_client
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise OpenAIClientError(f"openai SDK not installed: {exc}") from exc
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise OpenAIClientError("OPENAI_API_KEY is empty — set it or enable OPENAI_MOCK=true")
    _async_client = AsyncOpenAI(api_key=api_key)
    return _async_client


def is_available() -> bool:
    """True if we can actually call OpenAI (live or mock)."""
    if MOCK_ENABLED:
        return True
    return bool(os.getenv("OPENAI_API_KEY"))


async def call_openai(
    *,
    user_prompt:   str,
    system_prompt: Optional[str] = None,
    context_lines: Optional[list[str]] = None,
    json_schema:   Optional[dict] = None,
    model:         Optional[str] = None,
) -> OpenAIResult:
    """Send a prompt to OpenAI Chat Completions, return text + REAL usage."""
    if MOCK_ENABLED or not os.getenv("OPENAI_API_KEY"):
        return _mock_result(user_prompt=user_prompt, json_schema=json_schema, model=model)

    client = _get_client()
    use_model = model or DEFAULT_MODEL

    msgs: list[dict] = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    full_user = user_prompt
    if context_lines:
        full_user = full_user + "\n\n" + "\n".join(context_lines)
    msgs.append({"role": "user", "content": full_user})

    kwargs: dict = {"model": use_model, "messages": msgs}
    if json_schema:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name":   json_schema.get("title", "Output"),
                "strict": False,                      # strict mode requires extra schema work
                "schema": json_schema,
            },
        }

    t0 = time.time()
    try:
        resp = await client.chat.completions.create(**kwargs)
    except Exception as exc:
        raise OpenAIClientError(f"OpenAI call failed: {exc}") from exc
    dur = time.time() - t0

    choice = resp.choices[0]
    text = choice.message.content or ""
    usage = getattr(resp, "usage", None)
    tokens_in = getattr(usage, "prompt_tokens", 0) if usage else 0
    tokens_out = getattr(usage, "completion_tokens", 0) if usage else 0
    cached = 0
    if usage and getattr(usage, "prompt_tokens_details", None):
        cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0

    return OpenAIResult(
        text=text, model=use_model,
        tokens_in=tokens_in, tokens_out=tokens_out,
        duration_s=dur, cached_tokens=cached, mocked=False,
    )


def _mock_result(*, user_prompt: str, json_schema: Optional[dict],
                 model: Optional[str]) -> OpenAIResult:
    """Deterministic fake envelope so the pipeline can run without an API key."""
    if json_schema:
        # Walk the schema and emit a minimal-yet-valid object.
        body = _minimal_json_for_schema(json_schema)
        text = "```json\n" + json.dumps(body, indent=2) + "\n```"
    else:
        preview = (user_prompt or "")[:60]
        text = f"(MOCK) Echo: {preview}"
    return OpenAIResult(
        text=text, model=model or DEFAULT_MODEL,
        tokens_in=len(user_prompt) // 4, tokens_out=len(text) // 4,
        duration_s=0.0, cached_tokens=0, mocked=True,
    )


def _minimal_json_for_schema(schema: dict):
    """Generate a tiny example matching a JSON Schema (best-effort, mock only)."""
    t = schema.get("type")
    if "enum" in schema:
        # Prefer "neutral" enum values for the mock so post_validate hooks
        # don't trip on a synthetic mismatch (e.g. severity=info with no findings).
        for preferred in ("none", "info", "approve", "allow"):
            if preferred in schema["enum"]:
                return preferred
        return schema["enum"][0]
    if t == "object":
        out = {}
        for k in schema.get("required", []):
            out[k] = _minimal_json_for_schema(schema.get("properties", {}).get(k, {}))
        return out
    if t == "array":
        return []
    if t == "string":
        return "mock"
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "boolean":
        return False
    return None
