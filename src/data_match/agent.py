"""Data Match Agent — Steps 1-6 schema definition."""
from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd
from google.adk.agents import Agent
from google.adk.tools import FunctionTool, ToolContext

from .config import get_settings
from .file_parser import parse_file

_settings = get_settings()

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
    try:
        ictx = getattr(callback_context, "_invocation_context", None)
        if ictx is None or ictx.artifact_service is None:
            return

        user_content = getattr(ictx, "user_content", None)
        if user_content is None:
            return

        parts = getattr(user_content, "parts", None) or []
        existing = set(await callback_context.list_artifacts() or [])

        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline is None or getattr(inline, "data", None) is None:
                continue

            mime = (getattr(inline, "mime_type", "") or "").lower()
            display_name = getattr(part, "file_name", None) or ""

            if not (mime in {"text/csv", "application/csv", "application/vnd.ms-excel"} or display_name.lower().endswith((".csv", ".xlsx"))):
                continue

            if display_name and display_name not in existing:
                await callback_context.save_artifact(display_name, part)
                existing.add(display_name)

    except Exception as e:
        print(f"UPLOAD CALLBACK ERROR: {type(e).__name__}: {e}")
        raise


async def inspect_csv_row(
    filename: str,
    row_number: int = 0,
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """Show what's in a specific row of the CSV (1-indexed row number from user)."""
    try:
        if not tool_context:
            return {"error": "No tool context"}

        artifact = await tool_context.load_artifact(filename)
        file_bytes = _get_artifact_bytes(artifact)
        if not file_bytes:
            return {"error": f"Could not read {filename}"}

        df = pd.read_csv(BytesIO(file_bytes), header=None)
        row_idx = row_number - 1
        if row_idx < 0 or row_idx >= len(df):
            return {"error": f"Row {row_number} out of range (1-{len(df)})"}

        row_data = df.iloc[row_idx].tolist()
        row_str = " | ".join(str(x) if pd.notna(x) else "" for x in row_data)

        return {
            "status": "success",
            "filename": filename,
            "row_number": row_number,
            "row_content": row_str,
        }
    except Exception as e:
        return {"error": str(e)}


async def parse_with_header(
    filename: str,
    header_row: int = 0,
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """Parse CSV with specified header row (1-indexed from user, convert to 0-indexed)."""
    try:
        if not tool_context:
            return {"error": "No tool context"}

        artifact = await tool_context.load_artifact(filename)
        file_bytes = _get_artifact_bytes(artifact)
        if not file_bytes:
            return {"error": f"Could not read {filename}"}

        # Get the row content for display
        df_raw = pd.read_csv(BytesIO(file_bytes), header=None)
        row_idx = header_row - 1
        if row_idx >= 0 and row_idx < len(df_raw):
            row_content = " | ".join(str(x) if pd.notna(x) else "" for x in df_raw.iloc[row_idx].tolist())
        else:
            row_content = ""

        # Parse with the specified header
        header_idx = header_row - 1
        row_count, columns = parse_file(file_bytes, filename, header_row=header_idx)

        return {
            "status": "success",
            "filename": filename,
            "header_row": header_row,
            "row_content": row_content,
            "row_count": row_count,
            "columns": columns,
        }
    except Exception as e:
        return {"error": str(e)}


inspect_tool = FunctionTool(inspect_csv_row)
parse_tool = FunctionTool(parse_with_header)

root_agent = Agent(
    name="data_match",
    model=_settings.model,
    description="Data Match — Define comparison schemas (Steps 1-6)",
    instruction=_INSTRUCTION,
    tools=[inspect_tool, parse_tool],
    before_agent_callback=capture_uploaded_files_callback,
)
