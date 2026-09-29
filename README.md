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

**Artifact Service Instability**
- Second file may fail to load on first upload (transient artifact service issue)
- **Workaround**: Re-upload the file; works reliably on second attempt
- Issue is not in agent code—it's artifact service latency/timeout

**No External Persistence**
- Attempted GCS integration (callback upload) didn't work; removed to keep code simple
- No automatic save-to-database; users manually record schemas
- No multi-session schema retrieval

## How It Works

### Agent Architecture
- **Tool 1**: `inspect_csv_row()` — Shows row content for user verification
- **Tool 2**: `parse_with_header()` — Parses CSV at specified header row, returns columns & row count
- **Callback**: Captures uploaded Excel/CSV files and saves as artifacts
- **Memory Bank**: Stores artifact filenames after Step 1 confirmation; referenced in Steps 2-6

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

## Future Enhancements

- **Multi-session persistence**: Save schemas to Firestore/Cloud SQL
- **GCS integration**: Store CSVs in GCS for longer-term access
- **Schema versioning**: Track and retrieve previous schema definitions
- **Comparison engine integration**: Run actual data comparison from schema
