"""Provider router driven by policies/model_routing.yaml.

The whole reason this exists: Karpathy's "right-size models per task". Triage
doesn't need a frontier model; Validation does. Critic should come from a
DIFFERENT family than the producer (independent judge).

In the production deployment this system supports TWO providers, both
served by the single claude-cli-api gateway:
  - claude  → ClaudeProvider (gateway calls claude CLI)
  - gemini  → GeminiProvider (same gateway, backend=gemini)

OpenAIProvider lives in src/llm/openai.py for completeness but is NOT
registered here — production stack is claude+gemini only.

Override at runtime:
  * env AICICD_FORCE_PROVIDER=gemini      -> ignore per-agent routing, force gemini
  * env AICICD_FORCE_MODEL=gemini-2.5-pro -> override the model field
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import yaml

from src.config import POLICIES_DIR
from src.llm.base import LLMProvider
from src.llm.claude import ClaudeProvider
from src.llm.gemini import GeminiProvider


@dataclass
class Routing:
    provider: str
    model:    str


class Router:
    def __init__(self, config: dict):
        self.config = config
        self._providers: dict[str, LLMProvider] = {
            "claude": ClaudeProvider(),
            "gemini": GeminiProvider(),
        }

    @classmethod
    def from_default_config(cls) -> "Router":
        path = POLICIES_DIR / "model_routing.yaml"
        cfg = yaml.safe_load(path.read_text()) if path.exists() else {}
        return cls(cfg or {})

    def routing_for(self, agent_name: str) -> Routing:
        force_p = os.getenv("AICICD_FORCE_PROVIDER")
        force_m = os.getenv("AICICD_FORCE_MODEL")
        per_agent = (self.config.get("routing") or {}).get(agent_name) or {}
        default = self.config.get("default") or {"provider": "claude", "model": ""}
        provider = force_p or per_agent.get("provider") or default["provider"]
        model = force_m or per_agent.get("model") or default.get("model", "")
        return Routing(provider=provider, model=model)

    def provider(self, agent_name: str) -> tuple[LLMProvider, str]:
        r = self.routing_for(agent_name)
        prov = self._providers.get(r.provider)
        if prov is None:
            raise ValueError(
                f"unknown provider {r.provider!r} for agent {agent_name!r}; "
                f"production stack only supports {sorted(self._providers)}"
            )
        return prov, r.model


_singleton: Optional[Router] = None


def get_router() -> Router:
    global _singleton
    if _singleton is None:
        _singleton = Router.from_default_config()
    return _singleton
