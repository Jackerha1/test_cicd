"""LLM provider abstraction.

Providers expose a single async `call(...) -> CallResult`. Agents talk to a
`Router` that picks a provider per agent based on policies/model_routing.yaml.
This is the seam Karpathy would put: the rest of the system never imports
a vendor SDK directly.
"""
from src.llm.base import CallResult, LLMProvider, LLMError
from src.llm.router import Router, get_router

__all__ = ["CallResult", "LLMProvider", "LLMError", "Router", "get_router"]
