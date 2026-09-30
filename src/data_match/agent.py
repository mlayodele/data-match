"""Data Match Agent — Steps 1-6 schema definition."""
from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd
from google.adk.agents import Agent
from google.adk.tools import FunctionTool, ToolContext
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .config import get_settings
from .file_parser import parse_file

_settings = get_settings()
_tracer = trace.get_tracer(__name__)

_INSTRUCTION = """\
You are the Data Match Agent. Your job is to help users define comparison schemas
for comparing metrics across 2+ Excel/CSV files.

WORKFLOW (6 steps):

STEP 1: Upload & Parse Files
- Ask user to upload two files (Excel or CSV)
- After user uploads, list all available artifacts to identify which files are uploaded
- Store both artifact filenames in your memory bank for reference throughout the session
- For EACH uploaded file:
  * CRITICAL: Agent Q adds preamble rows (metadata, notes, etc.) before actual headers. Real headers are often on row 20-40, NOT row 1
  * Ask user: "What row number contains your ACTUAL column headers for [filename]? (e.g., 31, 25, etc.)"
  * User specifies row number (e.g., "row 31")
  * Before calling parse_with_header, verify the artifact still exists in the uploaded files
  * Call parse_with_header tool with that row number to:
    - Show the row content (so user can verify it's the header row)
    - Parse the CSV with that row as header
    - Get the detected column names
    - Show row count
  * Display results:
    - Filename
    - "Row [number] contains: [content]"
    - "Row count: [count]"
    - "Detected columns: [list]"
  * Ask user: "Do these columns look correct?"
  * User can:
    - Say "no, try row X" → Loop back to step above with new row number
    - Say "yes" → Confirm and move to next file
    - Say "yes but change X to Y, Z to W" → Confirm with manual edits
- Record the confirmed column names for both files
- **CRITICAL: After confirming headers for both files, explicitly save both artifact filenames to your memory bank.** You will reference these artifact names throughout Steps 2-6. Format: "File A artifact: [name] | File B artifact: [name]"

STEP 2: Define Match Key
- Retrieve the artifact filenames from your memory bank
- Ask: "Which columns identify a matching row? (e.g., ID, or ID + Date)"
- User specifies column mapping across files (e.g., "ID in File A maps to Client_ID in File B")
- Ask if there are other key fields
- Record the mapping

STEP 3: Define Metrics to Compare
- Retrieve the artifact filenames from your memory bank
- Ask: "Which columns should I compare?"
- User provides metric names (e.g., "Spend and Impressions")
- Agent suggests looking for same columns in both files, or asks for file-specific column names
- User clarifies if column names differ (e.g., "Spend is called Amount in File B")
- Record metric mappings (label, col_a, col_b)

STEP 4: Define Thresholds per Metric
- Retrieve the artifact filenames from your memory bank (if needed for context)
- For each metric, ask: "Threshold for [Metric]? (flag if difference exceeds...)"
- User provides in format: "5%" or "$1000" or "5% or $1000"
- Parse into: threshold_pct and/or threshold_units
- Confirm: "flag if [Metric] differs by more than X% OR $Y"

STEP 5: Apply Optional Row Filters
- Retrieve the artifact filenames from your memory bank
- Ask: "Any filters before comparing? (e.g., Display channel only, exclude certain dates)"
- If user specifies filter, ask for clarification: column name, keep/exclude mode, values
- Record filter(s)
- Ask if there are other filters

STEP 6: Confirm & Run
- Retrieve the artifact filenames from your memory bank
- Show summary of schema:
  * Files (with filter info and row counts)
  * Match key
  * Metrics with thresholds
  * Filters
- Ask: "Ready to compare?"
- If user confirms, the schema is ready for comparison execution

KEY PRINCIPLES:
- Ask ONE question at a time
- Be conversational and natural
- Show detected columns so user can make informed choices
- When user specifies columns, just record them (no validation)
- Confirm understanding at each step
- At Step 6, show full summary before asking to proceed

DEBUG:
- If user says "debug", "what files", or "show artifacts", use the debug_memory_bank tool
- This shows all uploaded files, their sizes, and whether they're accessible
- Helpful for troubleshooting file persistence issues

SCHEMA OUTPUT (for reference):
The schema is a JSON object containing:
- name: schema name
- key_columns: list of column names that identify matching rows
- metrics: list of metrics with label, col_a, col_b, threshold_pct, threshold_units
- filters: list of filters with file_idx, column, mode (keep/exclude), values
"""


def _get_artifact_bytes(artifact):
    """Extract bytes from artifact."""
    inline = getattr(artifact, "inline_data", None)
    if inline and getattr(inline, "data", None):
        return inline.data
    if getattr(artifact, "data", None):
        return artifact.data
    return None


async def capture_uploaded_files_callback(callback_context) -> None:
    """Capture uploaded files and save as artifacts."""
    with _tracer.start_as_current_span("capture_uploaded_files_callback") as span:
        try:
            ictx = getattr(callback_context, "_invocation_context", None)
            span.set_attribute("has_invocation_context", ictx is not None)
            if ictx is None or ictx.artifact_service is None:
                span.set_attribute("artifact_service_available", False)
                return

            span.set_attribute("artifact_service_available", True)

            user_content = getattr(ictx, "user_content", None)
            span.set_attribute("has_user_content", user_content is not None)
            if user_content is None:
                return

            parts = getattr(user_content, "parts", None) or []
            span.set_attribute("parts_count", len(parts))

            with _tracer.start_as_current_span("list_existing_artifacts") as list_span:
                existing = set(await callback_context.list_artifacts() or [])
                list_span.set_attribute("existing_artifacts_count", len(existing))
                list_span.set_attribute("existing_artifacts", list(existing))

            for i, part in enumerate(parts):
                with _tracer.start_as_current_span("process_upload_part") as part_span:
                    part_span.set_attribute("part_index", i)

                    inline = getattr(part, "inline_data", None)
                    if inline is None or getattr(inline, "data", None) is None:
                        part_span.set_attribute("has_inline_data", False)
                        continue

                    part_span.set_attribute("has_inline_data", True)

                    mime = (getattr(inline, "mime_type", "") or "").lower()
                    display_name = getattr(part, "file_name", None) or ""

                    part_span.set_attribute("mime_type", mime)
                    part_span.set_attribute("display_name", display_name)

                    if not (mime in {"text/csv", "application/csv", "application/vnd.ms-excel"} or display_name.lower().endswith((".csv", ".xlsx"))):
                        part_span.set_attribute("file_type_valid", False)
                        continue

                    part_span.set_attribute("file_type_valid", True)

                    if display_name and display_name not in existing:
                        with _tracer.start_as_current_span("save_artifact") as save_span:
                            save_span.set_attribute("filename", display_name)
                            save_span.set_attribute("is_new", True)
                            await callback_context.save_artifact(display_name, part)
                            existing.add(display_name)
                            save_span.set_attribute("save_status", "success")
                    else:
                        part_span.set_attribute("artifact_already_exists", True)

            span.set_attribute("final_artifacts_count", len(existing))
            span.set_attribute("final_artifacts", list(existing))

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            print(f"UPLOAD CALLBACK ERROR: {type(e).__name__}: {e}")
            raise


async def inspect_csv_row(
    filename: str,
    row_number: int = 0,
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """Show what's in a specific row of the CSV (1-indexed row number from user)."""
    with _tracer.start_as_current_span("inspect_csv_row") as span:
        span.set_attribute("filename", filename)
        span.set_attribute("row_number", row_number)

        try:
            if not tool_context:
                span.set_attribute("error", "No tool context")
                return {"error": "No tool context"}

            with _tracer.start_as_current_span("load_artifact") as load_span:
                load_span.set_attribute("filename", filename)
                artifact = await tool_context.load_artifact(filename)
                load_span.set_attribute("artifact_loaded", artifact is not None)

            file_bytes = _get_artifact_bytes(artifact)
            span.set_attribute("file_bytes_extracted", file_bytes is not None)
            if file_bytes is None:
                span.set_attribute("error", f"Could not read {filename}")
                return {"error": f"Could not read {filename}"}

            with _tracer.start_as_current_span("parse_csv") as parse_span:
                parse_span.set_attribute("file_size_bytes", len(file_bytes))
                df = pd.read_csv(BytesIO(file_bytes), header=None)
                parse_span.set_attribute("total_rows", len(df))
                parse_span.set_attribute("total_columns", len(df.columns))

            row_idx = row_number - 1
            span.set_attribute("row_index_0_based", row_idx)

            if row_idx < 0 or row_idx >= len(df):
                span.set_attribute("error", f"Row {row_number} out of range")
                return {"error": f"Row {row_number} out of range (1-{len(df)})"}

            row_data = df.iloc[row_idx].tolist()
            row_str = " | ".join(str(x) if pd.notna(x) else "" for x in row_data)

            span.set_attribute("row_content_length", len(row_str))
            span.set_attribute("row_values_count", len(row_data))
            span.set_status(Status(StatusCode.OK))

            return {
                "status": "success",
                "filename": filename,
                "row_number": row_number,
                "row_content": row_str,
            }
        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            return {"error": str(e)}


async def parse_with_header(
    filename: str,
    header_row: int = 0,
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """Parse CSV with specified header row (1-indexed from user, convert to 0-indexed)."""
    with _tracer.start_as_current_span("parse_with_header") as span:
        span.set_attribute("filename", filename)
        span.set_attribute("header_row", header_row)

        try:
            if not tool_context:
                span.set_attribute("error", "No tool context")
                return {"error": "No tool context"}

            with _tracer.start_as_current_span("load_artifact_for_parse") as load_span:
                load_span.set_attribute("filename", filename)
                artifact = await tool_context.load_artifact(filename)
                load_span.set_attribute("artifact_loaded", artifact is not None)
                if artifact is None:
                    load_span.set_attribute("error", "Artifact is None")

            file_bytes = _get_artifact_bytes(artifact)
            span.set_attribute("file_bytes_extracted", file_bytes is not None)
            if file_bytes is None:
                span.set_attribute("error", f"Could not extract bytes from {filename}")
                return {"error": f"Could not read {filename}"}

            span.set_attribute("file_size_bytes", len(file_bytes))

            # Get the row content for display
            with _tracer.start_as_current_span("parse_raw_for_preview") as preview_span:
                preview_span.set_attribute("header_row", header_row)
                df_raw = pd.read_csv(BytesIO(file_bytes), header=None)
                preview_span.set_attribute("total_rows", len(df_raw))
                preview_span.set_attribute("total_columns", len(df_raw.columns))

                row_idx = header_row - 1
                preview_span.set_attribute("row_index_0_based", row_idx)

                if row_idx >= 0 and row_idx < len(df_raw):
                    row_content = " | ".join(str(x) if pd.notna(x) else "" for x in df_raw.iloc[row_idx].tolist())
                    preview_span.set_attribute("header_row_found", True)
                    preview_span.set_attribute("header_content_length", len(row_content))
                else:
                    row_content = ""
                    preview_span.set_attribute("header_row_found", False)
                    preview_span.set_attribute("error", f"Header row {header_row} out of range")

            # Parse with the specified header
            with _tracer.start_as_current_span("parse_file_with_header") as parse_span:
                parse_span.set_attribute("filename", filename)
                parse_span.set_attribute("header_row", header_row)
                header_idx = header_row - 1
                row_count, columns = parse_file(file_bytes, filename, header_row=header_idx)
                parse_span.set_attribute("row_count", row_count)
                parse_span.set_attribute("columns_count", len(columns))
                parse_span.set_attribute("columns", columns)

            span.set_status(Status(StatusCode.OK))
            return {
                "status": "success",
                "filename": filename,
                "header_row": header_row,
                "row_content": row_content,
                "row_count": row_count,
                "columns": columns,
            }
        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.set_attribute("error", str(e))
            return {"error": str(e)}


async def debug_memory_bank(
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """Debug tool: list all available artifacts and memory state."""
    with _tracer.start_as_current_span("debug_memory_bank") as span:
        try:
            if not tool_context:
                return {"error": "No tool context"}

            with _tracer.start_as_current_span("list_artifacts_debug") as list_span:
                artifacts = await tool_context.list_artifacts() or []
                list_span.set_attribute("artifacts_count", len(artifacts))
                list_span.set_attribute("artifacts", artifacts)

            result = {
                "status": "success",
                "artifacts_available": artifacts,
                "artifacts_count": len(artifacts),
                "message": f"Found {len(artifacts)} artifact(s) in this session",
            }

            if artifacts:
                artifact_details = []
                for artifact_name in artifacts:
                    try:
                        with _tracer.start_as_current_span("debug_load_artifact") as load_span:
                            load_span.set_attribute("filename", artifact_name)
                            artifact = await tool_context.load_artifact(artifact_name)
                            file_bytes = _get_artifact_bytes(artifact)
                            size = len(file_bytes) if file_bytes else 0
                            load_span.set_attribute("file_size_bytes", size)
                            artifact_details.append({
                                "filename": artifact_name,
                                "size_bytes": size,
                                "size_kb": round(size / 1024, 2),
                                "loadable": file_bytes is not None,
                            })
                    except Exception as e:
                        load_span.record_exception(e)
                        artifact_details.append({
                            "filename": artifact_name,
                            "error": str(e),
                            "loadable": False,
                        })

                result["artifact_details"] = artifact_details

            span.set_status(Status(StatusCode.OK))
            return result

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            return {"error": str(e)}


inspect_tool = FunctionTool(inspect_csv_row)
parse_tool = FunctionTool(parse_with_header)
debug_tool = FunctionTool(debug_memory_bank)

root_agent = Agent(
    name="data_match",
    model=_settings.model,
    description="Data Match — Define comparison schemas (Steps 1-6)",
    instruction=_INSTRUCTION,
    tools=[inspect_tool, parse_tool, debug_tool],
    before_agent_callback=capture_uploaded_files_callback,
)
