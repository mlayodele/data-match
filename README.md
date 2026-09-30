# Reasoning Engine v2 — Data Match Schema Definition Agent

A Vertex AI Agent Engine application that guides users through defining comparison schemas for matching metrics across 2+ Excel/CSV files with inconsistently structured data.

## What It Does

The agent orchestrates a 6-step workflow to help users create schemas for data comparison:

1. **Upload & Parse Files** — Upload Excel/CSV files; agent detects column headers at user-specified rows
2. **Define Match Key** — Specify which columns identify matching rows across files  
3. **Define Metrics** — List which columns should be compared
4. **Define Thresholds** — Set tolerance levels (%, amount, or both) for metric differences
5. **Apply Row Filters** — Add optional filters before comparison
6. **Confirm & Run** — Review complete schema; ready for comparison execution

## What Works Well ✅

- **Session Persistence**: CSVs converted from Excel are stored as artifacts, accessible throughout the entire workflow
- **Flexible Header Detection**: Users specify which row contains real headers; agent shows content for verification
- **Natural Multi-File Workflow**: Handles 2+ files; stores and references both throughout all 6 steps
- **Column Validation**: Shows detected columns, allows manual edits before confirming
- **Memory Bank Integration**: Agent stores artifact filenames in memory; prevents "forgetting" files between steps

## Current Limitations ⚠️

**Session-Only Persistence**
- CSVs persist only for the current session; schema definitions are not saved
- Users must re-upload files if session ends
- Schema state exists in memory bank (users can copy/paste for manual persistence)

**Callback Unreliability**
- Upload callback may not work reliably; kept for potential future support
- Solution: Agent explicitly lists artifacts at Step 1 via `list_uploaded_files` tool
- This ensures agent always sees current state, regardless of callback success

**No External Persistence**
- No automatic save-to-database; users manually record schemas
- No multi-session schema retrieval
- All state is ephemeral (session-scoped only)

## How It Works

### Agent Architecture
- **Tool 1**: `list_uploaded_files()` — Lists all artifacts currently available (called at Step 1)
- **Tool 2**: `inspect_csv_row()` — Shows row content for user verification
- **Tool 3**: `parse_with_header()` — Parses CSV at specified header row, returns columns & row count
- **Tool 4**: `debug_memory_bank()` — Shows artifact contents for debugging
- **Callback**: Attempts to capture uploaded Excel/CSV files and save as artifacts (unreliable)
- **Memory Bank**: Stores artifact filenames after Step 1 confirmation; referenced in Steps 2-6
- **OpenTelemetry Tracing**: Granular spans track:
  - File uploads and artifact operations
  - Artifact loading and bytes extraction
  - CSV parsing and header detection
  - Tool execution with parameters and results
  - All errors and edge cases (missing files, out-of-range rows, etc.)

### File Handling
- Excel/CSV files uploaded → converted to artifacts by callback
- Filenames stored in memory bank (e.g., `Agent QA - DCM - ...csv`)
- Tools reference artifacts by filename; no external storage needed for session duration

## Deployment

```bash
python scripts/deploy_to_agent_engine.py --model gemini-2.5-flash create
python scripts/deploy_to_agent_engine.py --model gemini-2.5-flash update --resource-name projects/.../reasoningEngines/...
```

## Testing

1. Upload two Excel/CSV files
2. Specify header row for each file (agent shows row content for verification)
3. Confirm detected columns (or manually edit if needed)
4. Follow prompts through remaining 5 steps
5. Review final schema in memory bank

**Note**: If second file fails to load initially, re-upload it.

## Tracing & Debugging

All operations emit OpenTelemetry traces to Cloud Trace. Key instrumented flows:

**File Upload Flow**
- `capture_uploaded_files_callback`: Lists existing artifacts, processes each file part
  - Checks MIME type and filename extension
  - Saves new artifacts with filename as identifier
  - Tracks existing and final artifact counts

**Tool Execution (inspect_csv_row)**
- `load_artifact`: Attempts to load file by name from artifact service
- `parse_csv`: Reads file bytes, extracts requested row
- Attributes: filename, row number, row content length, total rows/columns

**Tool Execution (parse_with_header)**
- `load_artifact_for_parse`: Loads file and extracts bytes (critical for second-file debugging)
- `parse_raw_for_preview`: Validates header row exists, extracts content
- `parse_file_with_header`: Final parse with detected columns
- Attributes: filename, header row, file size, row count, column list

**Error Tracking**
- Every span records exceptions with full error messages
- "Cannot read file" errors trigger artifact_loaded and file_bytes_extracted checks
- Out-of-range row errors show total rows available

## Future Enhancements

- **Multi-session persistence**: Save schemas to Firestore/Cloud SQL
- **GCS integration**: Store CSVs in GCS for longer-term access
- **Schema versioning**: Track and retrieve previous schema definitions
- **Comparison engine integration**: Run actual data comparison from schema
