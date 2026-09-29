"""FunctionTool implementations for Data Match.

Pattern recap:
    1. Plain Python function (docstring + type hints become the tool spec).
    2. Wrap with FunctionTool(func=...) where the agent is built.
    3. Read secrets from os.environ — never .env at runtime.

For tools that need the live ADK runtime (artifacts, session, state), add
`tool_context: ToolContext` to the function signature — ADK injects it
automatically and hides it from the model-visible spec.
"""
__all__: list[str] = []






