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
from .comparison_engine import run_comparison

_settings = get_settings()
_tracer = trace.get_tracer(__name__)

_INSTRUCTION = """\
You are the Data Match Agent. Your job is to help users define comparison schemas
for comparing metrics across 2+ Excel/CSV files.

WORKFLOW (6 steps):

STEP 1: Upload & Parse Files
- Ask user to upload two files (Excel or CSV)
- After user uploads, IMMEDIATELY call discover_uploaded_files tool
  - This discovers the original Excel files and maps them to their converted CSVs
  - Agent Q converts each Excel sheet to a separate CSV automatically
- Show the user the original filenames discovered
- Store the original filenames and CSV mappings in your memory bank for reference throughout the session
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
- Show SCHEMA RECAP with: File A (header row, row count, all columns), File B (header row, row count, all columns)

STEP 2: Define Match Key
- Retrieve the artifact filenames from your memory bank
- Ask: "Which columns identify a matching row? (e.g., ID, or ID + Date)"
- User specifies column mapping across files (e.g., "ID in File A maps to Client_ID in File B")
- Ask if there are other key fields
- Record the mapping
- Show SCHEMA RECAP with all Step 1 details PLUS Match Keys (file A column = file B column)

STEP 2.5: Suggest & Confirm Match Key Types
- After user confirms match keys in STEP 2, IMMEDIATELY suggest data types for each match key:
  * IDs (columns with "ID" in name) → suggest "string"
  * Date/Time columns (name contains date/time/day/month) → suggest "date"
  * Other → suggest "string"
- Ask: "Do these types look correct? (Reply with types or say 'looks good')"
- User confirms or corrects the types
- CRITICAL: Create a match_key_types dict with EXACT match key column names:
  * Use the EXACT file_a_col names from the match keys you collected in STEP 2
  * Map each to its confirmed type: string, date, or number
  * Example structure: {"Placement ID": "string", "Date": "date", "Account": "string"}
  * Save this dict in your internal working memory for use in STEP 7
- Show SCHEMA RECAP with Match Keys including their confirmed types

STEP 3: Define Metrics to Compare
- Retrieve the artifact filenames from your memory bank
- Ask: "Which columns should I compare?"
- User provides metric names (e.g., "Spend and Impressions")
- Agent suggests looking for same columns in both files, or asks for file-specific column names
- User clarifies if column names differ (e.g., "Spend is called Amount in File B")
- Record metric mappings (label, col_a, col_b)
- Show SCHEMA RECAP with all Step 1 & 2 details PLUS Metrics (file A column = file B column)

STEP 4: Define Thresholds per Metric
- Retrieve the artifact filenames from your memory bank (if needed for context)
- For each metric, ask: "Threshold for [Metric]? (flag if difference exceeds...)"
- User provides in format: "5%" or "$1000" or "5% or $1000"
- Parse into: threshold_pct and/or threshold_units
- Confirm: "flag if [Metric] differs by more than X% OR $Y"
- Show SCHEMA RECAP with all Steps 1, 2, & 3 details PLUS Metrics & Thresholds (file A column = file B column | Threshold: X%)

STEP 5: Apply Optional Row Filters
- Retrieve the artifact filenames from your memory bank
- Ask: "Any filters before comparing? (e.g., Display channel only, exclude certain dates)"
- If user specifies filter, ask for clarification: column name, keep/exclude mode, values
- Record filter(s)
- Ask if there are other filters
- Show SCHEMA RECAP with all Steps 1-4 details PLUS Filters (column = value)

STEP 6: Confirm & Run
- Retrieve the artifact filenames from your memory bank
- Show COMPLETE SCHEMA RECAP with all details from Steps 1-5:
  * File A (header row, row count, all columns)
  * File B (header row, row count, all columns)
  * Match Keys
  * Metrics & Thresholds
  * Filters
- Ask: "Does this look correct? Are you ready to confirm and run the comparison?"
- If user confirms "yes", proceed to Step 7

STEP 7: Run Comparison Analysis
- User confirmed the schema in Step 6
- Files are already loaded in artifacts from Steps 1-6
- Show CONFIRMED SCHEMA DEFINITION (recap all details including match key types)
- CRITICAL: You MUST pass the match_key_types dict to the tool. This is essential for correct date/ID normalization.
- Call run_comparison_analysis tool with ALL parameters:
  * file_a_name: artifact filename (from memory bank)
  * file_b_name: artifact filename (from memory bank)
  * header_row_a: confirmed header row number (1-indexed)
  * header_row_b: confirmed header row number (1-indexed)
  * match_keys: list of {file_a_col, file_b_col} dicts (from STEP 2)
  * metrics: list of {name, file_a_col, file_b_col, threshold_pct} dicts (from STEP 3)
  * match_key_types: REQUIRED — dict with EXACT match key column names and types from STEP 2.5
    - MUST use exact file_a_col names as keys
    - Format: {"ColumnName1": "string", "ColumnName2": "date", ...}
    - Example: {"Placement ID": "string", "Date": "date", "Account": "string"}
    - Pass ALL match key columns with their confirmed types
    - DO NOT pass empty dict; ensure all types are specified
- Tool performs: load files → strip blank rows → aggregate by match key (normalizing types) → compare metrics → flag thresholds
- Tool returns: summary_stats, metric_totals, flagged_rows
- Display results directly:
  * Summary: Matched pairs, missing in A/B, total flagged count
  * Metric totals (File A, File B, difference, % difference)
  * Flagged rows: SHOW ONLY FIRST 100 ROWS (if total > 100, note "showing first 100 of X total flagged rows")

KEY PRINCIPLES:
- Ask ONE question at a time
- Be conversational and natural
- Show detected columns so user can make informed choices
- When user specifies columns, just record them (no validation)
- **At the end of EVERY step (Steps 1-6), show a persistent SCHEMA RECAP with all parameters collected so far**
- SCHEMA RECAP format: Parameter name → value (keep all details, never drop information)
- Maintain schema recap consistency throughout the entire conversation
- At Step 6, show complete schema recap before asking to proceed

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
    print("[CALLBACK] capture_uploaded_files_callback invoked")
    with _tracer.start_as_current_span("capture_uploaded_files_callback") as span:
        try:
            ictx = getattr(callback_context, "_invocation_context", None)
            print(f"[CALLBACK] invocation_context available: {ictx is not None}")
            span.set_attribute("has_invocation_context", ictx is not None)
            if ictx is None or ictx.artifact_service is None:
                print("[CALLBACK] artifact_service is None, returning")
                span.set_attribute("artifact_service_available", False)
                return

            print("[CALLBACK] artifact_service available")
            span.set_attribute("artifact_service_available", True)

            user_content = getattr(ictx, "user_content", None)
            span.set_attribute("has_user_content", user_content is not None)
            if user_content is None:
                return

            parts = getattr(user_content, "parts", None) or []
            print(f"[CALLBACK] found {len(parts)} parts to process")
            span.set_attribute("parts_count", len(parts))

            with _tracer.start_as_current_span("list_existing_artifacts") as list_span:
                existing = set(await callback_context.list_artifacts() or [])
                print(f"[CALLBACK] existing artifacts: {list(existing)}")
                list_span.set_attribute("existing_artifacts_count", len(existing))
                list_span.set_attribute("existing_artifacts", list(existing))

            for i, part in enumerate(parts):
                with _tracer.start_as_current_span("process_upload_part") as part_span:
                    part_span.set_attribute("part_index", i)
                    print(f"[CALLBACK] processing part {i}")

                    inline = getattr(part, "inline_data", None)
                    if inline is None or getattr(inline, "data", None) is None:
                        print(f"[CALLBACK] part {i} has no inline_data, skipping")
                        part_span.set_attribute("has_inline_data", False)
                        continue

                    part_span.set_attribute("has_inline_data", True)

                    mime = (getattr(inline, "mime_type", "") or "").lower()
                    display_name = getattr(part, "file_name", None) or ""

                    print(f"[CALLBACK] part {i}: mime={mime}, name={display_name}")
                    part_span.set_attribute("mime_type", mime)
                    part_span.set_attribute("display_name", display_name)

                    if not (mime in {"text/csv", "application/csv", "application/vnd.ms-excel"} or display_name.lower().endswith((".csv", ".xlsx"))):
                        print(f"[CALLBACK] part {i} file type invalid, skipping")
                        part_span.set_attribute("file_type_valid", False)
                        continue

                    part_span.set_attribute("file_type_valid", True)

                    if display_name and display_name not in existing:
                        print(f"[CALLBACK] saving artifact: {display_name}")
                        with _tracer.start_as_current_span("save_artifact") as save_span:
                            save_span.set_attribute("filename", display_name)
                            save_span.set_attribute("is_new", True)
                            await callback_context.save_artifact(display_name, part)
                            existing.add(display_name)
                            print(f"[CALLBACK] saved successfully: {display_name}")
                            save_span.set_attribute("save_status", "success")
                    else:
                        print(f"[CALLBACK] artifact already exists: {display_name}")
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


def _parse_converted_filename(csv_filename: str) -> dict[str, Any]:
    """Parse Agent Q converted CSV filename to extract original Excel name and sheet info.

    Pattern: [original_name].xlsx_Sheet[name]-[hash].csv
    Example: Agent QA - DCM - w.o 5.11 .xlsx_Sheet1_1503726_2026_version_Weekly_QA_.csv
    """
    if not csv_filename.endswith(".csv"):
        return {"original": None, "sheet": None}

    # Remove .csv extension
    base = csv_filename[:-4]

    # Look for .xlsx_Sheet pattern
    if ".xlsx_Sheet" not in base:
        return {"original": None, "sheet": None}

    # Split on .xlsx_Sheet
    parts = base.split(".xlsx_Sheet", 1)
    original_name = parts[0] + ".xlsx"  # Reconstruct original name
    sheet_info = parts[1] if len(parts) > 1 else None

    return {
        "original": original_name,
        "sheet": sheet_info,
        "csv_filename": csv_filename,
    }


async def discover_uploaded_files(
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """Gateway tool: Discover uploaded files and map CSVs back to original Excel files.

    Handles Agent Q's conversion where each Excel sheet becomes a separate CSV.
    Returns a mapping of original filenames to their constituent CSV files.
    """
    with _tracer.start_as_current_span("discover_uploaded_files") as span:
        try:
            if not tool_context:
                return {"error": "No tool context"}

            with _tracer.start_as_current_span("list_artifacts") as list_span:
                artifacts = await tool_context.list_artifacts() or []
                list_span.set_attribute("artifacts_count", len(artifacts))
                list_span.set_attribute("artifacts", artifacts)

            # Parse filenames to find original Excel files and their sheets
            excel_map: dict[str, list[dict]] = {}

            for csv_filename in artifacts:
                parsed = _parse_converted_filename(csv_filename)

                if parsed["original"]:
                    original = parsed["original"]
                    if original not in excel_map:
                        excel_map[original] = []
                    excel_map[original].append({
                        "csv_filename": csv_filename,
                        "sheet": parsed["sheet"],
                    })

            span.set_attribute("original_files_count", len(excel_map))
            span.set_attribute("original_files", list(excel_map.keys()))
            span.set_status(Status(StatusCode.OK))

            return {
                "status": "success",
                "original_files": list(excel_map.keys()),
                "file_count": len(excel_map),
                "file_mapping": excel_map,
                "message": f"Found {len(excel_map)} Excel file(s)" if excel_map else "No files uploaded yet",
            }

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            return {"error": str(e)}


async def list_uploaded_files(
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """List all uploaded files currently available as artifacts."""
    with _tracer.start_as_current_span("list_uploaded_files") as span:
        try:
            if not tool_context:
                return {"error": "No tool context"}

            with _tracer.start_as_current_span("list_artifacts") as list_span:
                artifacts = await tool_context.list_artifacts() or []
                list_span.set_attribute("artifacts_count", len(artifacts))
                list_span.set_attribute("artifacts", artifacts)

            span.set_status(Status(StatusCode.OK))
            return {
                "status": "success",
                "uploaded_files": artifacts,
                "file_count": len(artifacts),
                "message": f"Found {len(artifacts)} file(s)" if artifacts else "No files uploaded yet",
            }

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            return {"error": str(e)}


async def debug_memory_bank(
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """Debug tool: show all artifacts with preview of their contents."""
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
                "artifacts": {},
            }

            if artifacts:
                for artifact_name in artifacts:
                    try:
                        with _tracer.start_as_current_span("debug_load_artifact") as load_span:
                            load_span.set_attribute("filename", artifact_name)
                            artifact = await tool_context.load_artifact(artifact_name)
                            file_bytes = _get_artifact_bytes(artifact)

                            if file_bytes is None:
                                load_span.set_attribute("loadable", False)
                                result["artifacts"][artifact_name] = {
                                    "status": "failed",
                                    "error": "Could not extract bytes",
                                }
                                continue

                            size = len(file_bytes)
                            load_span.set_attribute("file_size_bytes", size)
                            load_span.set_attribute("loadable", True)

                            # Try to parse as CSV and show preview
                            try:
                                df = pd.read_csv(BytesIO(file_bytes), header=None, nrows=10)
                                preview_text = df.to_string()
                                result["artifacts"][artifact_name] = {
                                    "status": "loaded",
                                    "size_bytes": size,
                                    "size_kb": round(size / 1024, 2),
                                    "total_rows_visible": len(df),
                                    "columns": len(df.columns),
                                    "preview": preview_text,
                                }
                            except Exception as parse_e:
                                # If not CSV, just show raw content
                                content = file_bytes.decode('utf-8', errors='replace')[:500]
                                result["artifacts"][artifact_name] = {
                                    "status": "loaded",
                                    "size_bytes": size,
                                    "size_kb": round(size / 1024, 2),
                                    "parse_error": str(parse_e),
                                    "raw_preview": content,
                                }

                    except Exception as e:
                        load_span.record_exception(e)
                        result["artifacts"][artifact_name] = {
                            "status": "error",
                            "error": str(e),
                        }

            span.set_status(Status(StatusCode.OK))
            return result

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            return {"error": str(e)}


def format_comparison_results(results: dict[str, Any]) -> dict[str, Any]:
    """Format comparison results for display with type conversion verification.

    Shows summary stats, metric totals, flagged rows, and DEBUG section with:
    - Types applied (inferred or passed by user)
    - Sample match keys from both files (to verify type conversion)
    - Type conversion check (warns if .0 artifacts present)
    """
    with _tracer.start_as_current_span("format_comparison_results") as span:
        try:
            output_lines = []
            output_lines.append("=" * 80)
            output_lines.append("COMPARISON ANALYSIS RESULTS")
            output_lines.append("=" * 80)

            # Summary stats
            if "summary_stats" in results:
                stats = results["summary_stats"]
                output_lines.append("\nSummary Statistics:")
                output_lines.append(f"  • Matched Pairs: {stats.get('matched_pairs', 0)}")
                output_lines.append(f"  • Missing in File A: {stats.get('missing_in_a', 0)}")
                output_lines.append(f"  • Missing in File B: {stats.get('missing_in_b', 0)}")
                output_lines.append(f"  • Total Flagged Rows: {stats.get('flagged_count', 0)}")

            # Metric totals
            if "metric_totals" in results:
                output_lines.append("\nMetric Totals:")
                for metric_name, values in results["metric_totals"].items():
                    output_lines.append(f"\n  {metric_name}:")
                    output_lines.append(f"    • File A Total: {values.get('file_a', 0)}")
                    output_lines.append(f"    • File B Total: {values.get('file_b', 0)}")
                    output_lines.append(f"    • Difference: {values.get('delta', 0):.2f}")
                    output_lines.append(f"    • Percentage Difference: {values.get('delta_pct', 0):.2f}%")

            # DEBUG: Type inference and key samples
            output_lines.append("\n" + "=" * 80)
            output_lines.append("DEBUG: Type Inference & Match Key Samples")
            output_lines.append("=" * 80)

            if "_debug" in results:
                debug = results["_debug"]

                output_lines.append(f"\nTypes Passed by Agent: {debug.get('match_key_types_passed_by_agent', False)}")
                output_lines.append(f"Types Applied: {debug.get('match_key_types_applied', {})}")
                output_lines.append(f"Note: {debug.get('note', 'N/A')}")

                output_lines.append(f"\n\nFile A Unique Keys: {debug.get('file_a_unique_keys', 0)}")
                output_lines.append("File A Sample Keys (first 5):")
                for key in debug.get('file_a_agg_keys_sample', []):
                    output_lines.append(f"  • {key}")

                output_lines.append(f"\n\nFile B Unique Keys: {debug.get('file_b_unique_keys', 0)}")
                output_lines.append("File B Sample Keys (first 5):")
                for key in debug.get('file_b_agg_keys_sample', []):
                    output_lines.append(f"  • {key}")

                # Type conversion check
                keys_a = debug.get('file_a_agg_keys_sample', [])
                keys_b = debug.get('file_b_agg_keys_sample', [])

                output_lines.append("\n" + "-" * 80)
                output_lines.append("TYPE CONVERSION VERIFICATION:")
                output_lines.append("-" * 80)

                float_keys_a = [k for k in keys_a if '.0|' in k or k.endswith('.0')]
                float_keys_b = [k for k in keys_b if '.0|' in k or k.endswith('.0')]

                if float_keys_a or float_keys_b:
                    output_lines.append("⚠️  WARNING: Float artifacts (.0) detected!")
                    if float_keys_a:
                        output_lines.append(f"  File A has {len(float_keys_a)} keys with .0: {float_keys_a[:3]}")
                    if float_keys_b:
                        output_lines.append(f"  File B has {len(float_keys_b)} keys with .0: {float_keys_b[:3]}")
                    output_lines.append("  → Type conversion NOT working correctly")
                else:
                    output_lines.append("✓ GOOD: No float artifacts (.0) detected in match keys")
                    output_lines.append("  → Types are being converted correctly")

            # Flagged rows (first 10)
            if "flagged_rows" in results and results["flagged_rows"]:
                flagged = results["flagged_rows"][:10]
                total_flagged = len(results["flagged_rows"])

                output_lines.append("\n" + "=" * 80)
                output_lines.append(f"Flagged Rows (showing first {len(flagged)} of {total_flagged} total):")
                output_lines.append("=" * 80)

                for row in flagged:
                    output_lines.append(f"\n  Match Key: {row.get('match_key', 'N/A')}")
                    output_lines.append(f"  Status: {row.get('status', 'N/A')}")
                    if row.get('file_a_metrics'):
                        for metric, val in row['file_a_metrics'].items():
                            output_lines.append(f"    File A {metric}: {val}")
                    if row.get('file_b_metrics'):
                        for metric, val in row['file_b_metrics'].items():
                            output_lines.append(f"    File B {metric}: {val}")

            output_lines.append("\n" + "=" * 80)

            span.set_attribute("formatted", True)
            return {
                "status": "success",
                "formatted_results": "\n".join(output_lines),
            }

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            return {"error": str(e)}


async def run_comparison_analysis(
    context: ToolContext,
    file_a_name: str,
    file_b_name: str,
    header_row_a: int,
    header_row_b: int,
    match_keys: list[dict[str, str]],
    metrics: list[dict[str, Any]],
    match_key_types: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run comparison analysis on two files using confirmed schema.

    Loads files from artifacts (same pattern as parse_with_header).
    Aggregates rows by match key, compares metrics, flags threshold breaches.

    Args:
        match_key_types: Dict mapping match key names to types (string, date, etc.)
    """
    with _tracer.start_as_current_span("run_comparison_analysis") as span:
        try:
            span.set_attribute("file_a", file_a_name)
            span.set_attribute("file_b", file_b_name)
            span.set_attribute("match_keys_count", len(match_keys))
            span.set_attribute("metrics_count", len(metrics))

            # Load files using same technique as parse_with_header
            with _tracer.start_as_current_span("load_artifact_for_comparison") as load_span:
                artifact_a = await context.load_artifact(file_a_name)
                artifact_b = await context.load_artifact(file_b_name)
                load_span.set_attribute("artifact_a_loaded", artifact_a is not None)
                load_span.set_attribute("artifact_b_loaded", artifact_b is not None)

            file_a_bytes = _get_artifact_bytes(artifact_a)
            file_b_bytes = _get_artifact_bytes(artifact_b)

            if file_a_bytes is None or file_b_bytes is None:
                return {"error": f"Could not read files"}

            # Run comparison: load → aggregate → compare → flag
            with _tracer.start_as_current_span("run_comparison_engine") as cmp_span:
                result = run_comparison(
                    file_a_bytes=file_a_bytes,
                    file_b_bytes=file_b_bytes,
                    header_row_a=header_row_a,
                    header_row_b=header_row_b,
                    match_keys=match_keys,
                    metrics=metrics,
                    match_key_types=match_key_types,
                )
                cmp_span.set_attribute("status", "success")

            span.set_status(Status(StatusCode.OK))
            return result

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            return {"error": str(e)}


discover_tool = FunctionTool(discover_uploaded_files)
inspect_tool = FunctionTool(inspect_csv_row)
parse_tool = FunctionTool(parse_with_header)
list_files_tool = FunctionTool(list_uploaded_files)
debug_tool = FunctionTool(debug_memory_bank)
comparison_tool = FunctionTool(run_comparison_analysis)
format_results_tool = FunctionTool(format_comparison_results)

root_agent = Agent(
    name="data_match",
    model=_settings.model,
    description="Data Match — Define schemas and run comparisons",
    instruction=_INSTRUCTION,
    tools=[discover_tool, list_files_tool, inspect_tool, parse_tool, debug_tool, comparison_tool, format_results_tool],
    before_agent_callback=capture_uploaded_files_callback,
)
