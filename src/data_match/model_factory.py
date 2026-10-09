"""Model construction pinned to the right Vertex region.

Gemini 3.x (including gemini-3.7-flash) is served ONLY from the `global`
Vertex endpoint and returns 404 in us-central1. The Agent Engine is a
regional resource that must stay on `Settings.location`, so the model
endpoint needs its own knob — `Settings.model_location`.

Why this is a module and not a one-liner in `agent.py`: ADK only grew the
supported hook for this (`Gemini.client_kwargs`) in 2.4/2.5. On older versions
pydantic silently DROPS the unknown kwarg rather than raising, so a naive
`Gemini(model=..., client_kwargs=...)` looks correct, deploys green, and then
404s on every turn. We detect the capability instead of assuming it.
"""
from __future__ import annotations

import os

from google.adk.models import Gemini

from .config import get_settings

_SUPPORTS_CLIENT_KWARGS = "client_kwargs" in Gemini.model_fields


def build_model() -> Gemini:
    """The agent's model, with its genai client pinned to `model_location`."""
    settings = get_settings()
    if _SUPPORTS_CLIENT_KWARGS:
        return Gemini(
            model=settings.model,
            client_kwargs={"location": settings.model_location},
        )

    from google.genai import Client, types

    gemini = Gemini(model=settings.model)
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "1") != "1":
        return gemini
    # Seed the `api_client` cached_property before anything reads it. Mirrors
    # what ADK builds, so its telemetry headers survive.
    http_options = types.HttpOptions()
    tracking = getattr(gemini, "_tracking_headers", None)
    if callable(tracking):
        try:
            http_options.headers = tracking()
        except Exception:  # pragma: no cover - telemetry is best-effort
            pass
    gemini.__dict__["api_client"] = Client(
        vertexai=True,
        project=settings.gcp_project or None,
        location=settings.model_location,
        http_options=http_options,
    )
    return gemini
