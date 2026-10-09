"""Typed env loader.

Why this module exists: every project reads config the SAME way. The deployed
container has an empty .env — values come from agentq.config.yaml runtime.env_vars
which arrive as real environment variables. Centralising the read here means:
- One place to add a new setting.
- Tools and agents depend on `settings`, not on os.environ scattered everywhere.
- Easy to swap the backend later (e.g. Secret Manager) without touching agents.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    model: str
    gcp_project: str
    location: str
    # Vertex location for the *model* endpoint only — deliberately separate
    # from `location`. The Gemini 3.x family (incl. gemini-3.7-flash) is served
    # exclusively from the `global` endpoint and 404s in us-central1, while the
    # Agent Engine is a regional resource that must stay on `location`.
    # Collapsing the two would break one or the other.
    model_location: str



def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise EnvironmentError(
            f"Missing required environment variable: {name}. "
            "Locally: copy .env.example → .env. "
            "In Agent Engine: ensure runtime.env_vars in agentq.config.yaml."
        )
    return val


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        model=os.environ.get("MODEL_ID", os.environ.get("MODEL", "gemini-3.7-flash")),
        gcp_project=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        model_location=os.environ.get("MODEL_LOCATION", "global"),
    )
