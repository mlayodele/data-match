#!/usr/bin/env python3
"""Deploy Data Match Agent to Vertex AI Agent Engine.

Usage:
    python scripts/deploy_to_agent_engine.py --model <MODEL> create
    python scripts/deploy_to_agent_engine.py --model <MODEL> update --resource-name <NAME>
    python scripts/deploy_to_agent_engine.py list
    python scripts/deploy_to_agent_engine.py delete --resource-name <NAME>
    python scripts/deploy_to_agent_engine.py query --resource-name <NAME> --message <MSG>

Examples:
    # Create new engine
    python scripts/deploy_to_agent_engine.py --model gemini-2.5-flash create

    # Update existing engine
    python scripts/deploy_to_agent_engine.py --model gemini-2.5-flash update --resource-name projects/.../reasoningEngines/...

Environment Variables (optional):
    MODEL                    — Gemini model to use (default: gemini-2.5-flash)
    GCS_PROJECT_ID           — GCP project ID (default: horizon-ai-462013)
    GCS_STAGING_BUCKET       — GCS bucket for staging (default: gs://horizon-ai-462013-agentq-staging)
    GOOGLE_GENAI_USE_VERTEXAI — Set to "1" to use Vertex AI (default: 1)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"

DEFAULT_PROJECT = "horizon-ai-462013"
DEFAULT_LOCATION = "us-central1"
DEFAULT_STAGING_BUCKET = "gs://horizon-ai-462013-agentq-staging"
DEFAULT_SERVICE_ACCOUNT = "agentq-runtime-staging@horizon-ai-462013.iam.gserviceaccount.com"
DEFAULT_DISPLAY_NAME = "Data Match"
DEFAULT_MODEL = os.getenv("MODEL", "gemini-2.5-flash")

# Requirements for data match agent
REQUIREMENTS = [
    "google-adk>=0.1.0",
    "google-genai>=0.1.0",
    "google-cloud-aiplatform>=1.0.0",
    "pandas>=2.0.0",
    "openpyxl>=3.0.0",
    "google-cloud-storage>=2.0.0",
    "opentelemetry-api>=1.20.0",
    "opentelemetry-sdk>=1.20.0",
    "opentelemetry-exporter-gcp-trace>=1.5.0",
    "opentelemetry-exporter-otlp-proto-http>=0.41b0",
]


def _run(cmd: list[str]) -> None:
    """Run a command."""
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def _init_vertex(project: str, location: str, staging_bucket: str) -> None:
    """Initialize Vertex AI."""
    import vertexai
    vertexai.init(project=project, location=location, staging_bucket=staging_bucket)


def _build_env_vars(args: argparse.Namespace) -> dict[str, str]:
    """Build environment variables for agent."""
    env: dict[str, str] = {}
    env["MODEL_ID"] = args.model
    env["GCP_PROJECT"] = args.project
    env["LOCATION"] = args.location
    env["GOOGLE_GENAI_USE_VERTEXAI"] = "1"
    return env


def _build_adk_app(model: str):
    """Construct the AdkApp wrapping the data match agent."""
    os.environ.setdefault("MODEL_ID", model)
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "1")

    from vertexai.agent_engines import AdkApp
    from data_match.agent import root_agent

    return AdkApp(agent=root_agent, enable_tracing=True)


def _with_src_layout(fn):
    """Run fn() with cwd set to src/ so extra_packages=["data_match"] resolves correctly."""
    original_cwd = os.getcwd()
    inserted = str(_SRC) not in sys.path
    if inserted:
        sys.path.insert(0, str(_SRC))
    os.chdir(_SRC)
    try:
        return fn()
    finally:
        os.chdir(original_cwd)
        if inserted:
            sys.path.remove(str(_SRC))


def cmd_create(args: argparse.Namespace) -> int:
    """Create a new agent engine."""
    _init_vertex(args.project, args.location, args.staging_bucket)
    from vertexai import agent_engines

    env_vars = _build_env_vars(args)

    print(f"\n{'='*60}")
    print(f"CREATING NEW DATA MATCH ENGINE")
    print(f"{'='*60}")
    print(f"Project: {args.project}")
    print(f"Location: {args.location}")
    print(f"Model: {args.model}")
    print(f"Staging bucket: {args.staging_bucket}")
    print(f"Requirements: {len(REQUIREMENTS)} packages")
    print(f"Env vars: {sorted(env_vars.keys())}")
    print(f"Tools: list_uploaded_files, inspect_csv_row, parse_with_header, debug_memory_bank")
    print(f"Callback: capture_uploaded_files_callback")
    print(f"\nThis may take several minutes...\n")

    def _deploy_create():
        app = _build_adk_app(args.model)
        return agent_engines.create(
            agent_engine=app,
            requirements=REQUIREMENTS,
            extra_packages=["data_match"],
            env_vars=env_vars,
            display_name=args.display_name,
            description="Data Match — Guides users through defining unified schemas for aggregating data across inconsistently-structured files.",
            service_account=args.service_account,
        )

    remote_app = _with_src_layout(_deploy_create)

    print(f"\n✓ Deployment created: {remote_app.resource_name}")
    print(f"  Display name: {remote_app.display_name}")
    print(f"  Model: {args.model}")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    """Update an existing agent engine."""
    if not args.resource_name:
        print("ERROR: --resource-name required for update")
        return 1

    _init_vertex(args.project, args.location, args.staging_bucket)
    from vertexai import agent_engines

    env_vars = _build_env_vars(args)

    print(f"\n{'='*60}")
    print(f"UPDATING DATA MATCH ENGINE")
    print(f"{'='*60}")
    print(f"Resource: {args.resource_name}")
    print(f"Model: {args.model}")
    print(f"Env vars: {sorted(env_vars.keys())}")
    print(f"Tools: list_uploaded_files, inspect_csv_row, parse_with_header, debug_memory_bank")
    print(f"Callback: capture_uploaded_files_callback")
    print(f"\nThis may take several minutes...\n")

    def _deploy_update():
        app = _build_adk_app(args.model)
        return agent_engines.update(
            agent_engine=app,
            resource_name=args.resource_name,
            requirements=REQUIREMENTS,
            extra_packages=["data_match"],
            env_vars=env_vars,
        )

    remote_app = _with_src_layout(_deploy_update)

    print(f"\n✓ Update complete: {remote_app.resource_name}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List agent engines."""
    _init_vertex(args.project, args.location, args.staging_bucket)
    from vertexai import agent_engines

    apps = agent_engines.list()
    print(f"\nAgent Engines in {args.project}/{args.location}:")
    for app in apps:
        print(f"  - {app.resource_name}")
        print(f"    Display name: {app.display_name}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    """Delete an agent engine."""
    if not args.resource_name:
        print("ERROR: --resource-name required for delete")
        return 1

    _init_vertex(args.project, args.location, args.staging_bucket)
    from vertexai import agent_engines

    confirm = input(f"Delete {args.resource_name}? Type 'yes' to confirm: ")
    if confirm != "yes":
        print("Cancelled.")
        return 1

    agent_engines.delete(args.resource_name)
    print(f"✓ Deleted: {args.resource_name}")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    """Query an agent engine."""
    if not args.resource_name:
        print("ERROR: --resource-name required for query")
        return 1
    if not args.message:
        print("ERROR: --message required for query")
        return 1

    _init_vertex(args.project, args.location, args.staging_bucket)
    from vertexai import agent_engines

    app = agent_engines.get(args.resource_name)
    response = app.query(input_=args.message)

    print(f"\nQuery: {args.message}")
    print(f"Response: {response}")
    return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Deploy Data Match to Vertex AI Agent Engine"
    )

    # Global arguments (before subcommand)
    parser.add_argument(
        "--project",
        default=DEFAULT_PROJECT,
        help=f"GCP project ID (default: {DEFAULT_PROJECT})",
    )
    parser.add_argument(
        "--location",
        default=DEFAULT_LOCATION,
        help=f"GCP location (default: {DEFAULT_LOCATION})",
    )
    parser.add_argument(
        "--staging-bucket",
        default=DEFAULT_STAGING_BUCKET,
        help=f"GCS staging bucket (default: {DEFAULT_STAGING_BUCKET})",
    )
    parser.add_argument(
        "--service-account",
        default=DEFAULT_SERVICE_ACCOUNT,
        help=f"Service account (default: {DEFAULT_SERVICE_ACCOUNT})",
    )
    parser.add_argument(
        "--display-name",
        default=DEFAULT_DISPLAY_NAME,
        help=f"Display name (default: {DEFAULT_DISPLAY_NAME})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Gemini model (default: {DEFAULT_MODEL})",
    )

    # Subcommands (after global arguments)
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("create", help="Create a new agent engine")

    update_parser = subparsers.add_parser("update", help="Update an existing agent engine")
    update_parser.add_argument("--resource-name", required=True, help="Resource name to update")

    subparsers.add_parser("list", help="List agent engines")

    delete_parser = subparsers.add_parser("delete", help="Delete an agent engine")
    delete_parser.add_argument("--resource-name", required=True, help="Resource name to delete")

    query_parser = subparsers.add_parser("query", help="Query an agent engine")
    query_parser.add_argument("--resource-name", required=True, help="Resource name to query")
    query_parser.add_argument("--message", required=True, help="Message to send")

    args = parser.parse_args()

    if args.command == "create":
        return cmd_create(args)
    elif args.command == "update":
        return cmd_update(args)
    elif args.command == "list":
        return cmd_list(args)
    elif args.command == "delete":
        return cmd_delete(args)
    elif args.command == "query":
        return cmd_query(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
