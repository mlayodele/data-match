"""Pipeline stage: stage_1.

Stages share state via session.state. Set output_key to publish this stage's
final reply, then read it from a later stage with {output_key} in the
instruction template.
"""
from __future__ import annotations

from google.adk.agents import LlmAgent

from ..config import get_settings


_settings = get_settings()


stage_1 = LlmAgent(
    name="stage_1",
    model=_settings.model,
    description="TODO: what stage 1 does",
    instruction=(
        "You are pipeline stage 1 (stage_1). "
        "TODO: describe inputs (read from state via {previous_key}) "
        "and the expected output."
    ),
    output_key="stage_1",
)
