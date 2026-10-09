# Investigation: Synthetic Test Files Fail to Upload/Load

**Status:** UNRESOLVED — reverted to main, not blocking production use  
**Date:** 2026-10-06 to 2026-10-07  
**Affected files:** `Sales_System_A.xlsx`, `Sales_System_B.xlsx` (synthetic test data in `/Users/mayodele/Desktop/Data Match 2/comparison files/`)  
**Unaffected (work fine):** `Agent QA - Swivel - w.o 5.11.xlsx`, `Agent QA - DCM - w.o 5.11 .xlsx`, `HX Dashboard data - week of 5.11.xlsx`

---

## The Problem

When uploading `Sales_System_A.xlsx` / `Sales_System_B.xlsx` to the Data Match Agent (via Gemini Enterprise / Agent Q), the agent consistently fails to load them — across many attempts, in fresh sessions, across multiple regenerated versions of the files. Error messages vary across runs ("provided as text, not uploaded," "trouble accessing the file," "didn't register immediately," "not uploaded successfully") but the underlying outcome is always the same: **the file never becomes a loadable artifact.**

The three real business files (Swivel, DCM, HX) have never once failed across extensive testing in this same period.

---

## Why This Was Hard to Debug

Error messages reported by the agent are **Gemini's own narration**, not grounded tool output. The agent fabricates plausible-sounding filenames/explanations when it doesn't have real tool results (observed directly: it guessed `Sales_System_A.xlsx_Sheet1_Sheet1.csv` before any tool had confirmed that name). This means four different-sounding errors across four runs could all represent the exact same underlying failure — **don't trust the chat transcript as evidence of which pipeline stage failed.**

The real pipeline has three stages, only one of which we can fully inspect:
1. **Agent Q's upload/conversion** (xlsx → CSV) — total black box, no logs accessible to us
2. **Our code** (`capture_uploaded_files_callback`, `discover_uploaded_files`, `load_artifact` calls) — fully instrumented with OTel spans and print statements, but **we never actually pulled these logs/traces for a failed run** — everything was inferred from chat transcripts instead. This is the single biggest gap in the investigation — see "Next Steps" below.
3. **Vertex's artifact service** (GCS-backed, injected via `ictx.artifact_service`) — black box, no visibility into read-after-write consistency guarantees

---

## Hypotheses Tested (all ruled out as sufficient fixes)

### 1. OOXML structural validity (inline strings vs. shared strings)
**Finding:** The original test files, generated via `openpyxl.Workbook()`, were missing `xl/sharedStrings.xml` and the XML declaration, and used `t="inlineStr"` instead of `t="s"` + shared string table. All three working files use the shared-strings format (the universal standard every real spreadsheet tool produces; inline strings are spec-valid but rarely seen in the wild).

**Fix applied:** Regenerated both files using `xlsxwriter` engine instead of `openpyxl`, confirmed via raw zip/XML inspection that output now matches working files' structure exactly (shared strings + XML declaration present).

**Result:** Did not fix the issue.

### 2. Generic vs. distinctive internal sheet tab name
**Finding:** All three working files have a distinctive, non-default internal Excel worksheet tab name (not the literal string "Sheet1"):
- DCM: `1503726_2026_version_Weekly_QA_`
- Swivel: `report-2026-05-20-0be5e487ba35`
- HX: `week of 5.11`

Our synthetic files had the library default tab name `Sheet1`. Confirmed the converted CSV filename pattern is `[original].xlsx_Sheet{index}_{actual_tab_name}.csv` — i.e. Agent Q's naming scheme literally echoes the sheet's internal tab name. Our degenerate tab name produced degenerate/colliding CSV names (`Sheet1_Sheet1.csv`, inconsistently `Sheet1_Sheet.csv` across runs).

**Fix applied:** Renamed worksheet tabs to `SystemA_Q1_2026` / `SystemB_Q1_2026`.

**Result:** Agent Q *did* correctly use the new tab name in the converted filename (`Sales_System_A.xlsx_Sheet1_SystemA_Q1_2026.csv` — confirming our understanding of the naming convention was correct), but the file **still failed to load** afterward. Naming was fixed; loading still broken.

### 3. Missing ADK `load_artifacts` tool
**Finding:** [google/adk-python#4928](https://github.com/google/adk-python/issues/4928) documents: "Artifacts are silently dropped or ignored when uploaded to an agent on Vertex AI Agent Engine if `load_artifacts` is not in the agent's tools." Our agent's tool list never included ADK's built-in `load_artifacts` tool — only our own custom tools that call `tool_context.load_artifact()` directly. This also seemed to explain earlier historical symptoms from this project ("artifacts kept getting forgotten," "doesn't work unless we reupload the file").

**Fix applied:** Added `from google.adk.tools import load_artifacts` and included it in the agent's `tools=[...]` list. Verified it imports and the agent loads correctly.

**Result:** Deployed and tested — **did not fix the test files**, and (as expected if this wasn't the issue for them anyway) made no difference to Swivel/DCM, which continued working regardless.

**Note:** User mentioned having tried `load_artifacts` once before independently and running into problems, though details weren't captured — worth asking again if this is revisited.

---

## Current State

- `agent.py` reverted to match `origin/main` (no `load_artifacts`, no other changes from this investigation)
- Test files remain in `/Users/mayodele/Desktop/Data Match 2/comparison files/Sales_System_A.xlsx` and `...B.xlsx`, currently in the "fixed structure + fixed tab name" state (xlsxwriter-generated, shared strings, distinctive tab names) — this state has NOT been reverted, only the agent code was
- Production files (Swivel/DCM/HX) unaffected throughout; this is not blocking real usage

---

## Next Steps (when picking this back up)

1. **Pull actual OTel traces / stdout logs** for `capture_uploaded_files_callback` and `discover_uploaded_files` from a real failed run with these files. This is the biggest unexploited lead — we have detailed instrumentation (`parts_count`, `has_inline_data`, `mime_type`, `display_name`, `artifacts_count`, `artifacts` span attributes + matching `print()` statements) that has never actually been inspected. Check Vertex AI Agent Engine logs/Cloud Logging for the relevant session.
2. **Check `docProps/app.xml` / `core.xml` metadata** — real exports show the actual source application as creator; our synthetic files show `xlsxwriter`/`openpyxl`. Untested, low-cost, long-shot.
3. Consider testing with a **real file that happens to have a small size** (to isolate file size/complexity as a variable, independent of "is it synthetic") — never cleanly isolated this variable.
4. Consider asking Google/Gemini Enterprise platform support directly, since steps 1-3 within our own code/data have been exhausted without resolution, and the remaining black boxes (Agent Q conversion, Vertex artifact service internals) aren't things we can instrument ourselves.
