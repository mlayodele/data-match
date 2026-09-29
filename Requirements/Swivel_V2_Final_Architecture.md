# Metric QA Agent v2 – Final Architecture

## What We're Building

A conversational AI agent (Google Gemini) that lets Horizon employees compare metrics across 2+ Excel/CSV files, automatically flag discrepancies, and export reports. Based on the proven DataMatch QA Tool (HTML version), upgraded to Gemini Enterprise for conversational access.

---

## Key Specs (Finalized)

| Spec | Value |
|------|-------|
| **File Format** | Excel (.xlsx) or CSV only |
| **Sharepoint Integration** | Manual: user pastes URL, agent downloads |
| **Report Output** | Flagged rows only (no "show all rows" option) |
| **Dynamic Filters (Post-Run)** | Key values + Hide zeros |

---

## How It Works (3 Steps)

**Step 1: Upload & Configure** → **Step 2: Run Comparison** → **Step 3: Review & Export**

User uploads files or pastes Sharepoint URL → Agent parses headers, user confirms match keys & metrics → Agent runs 3-stage pipeline (load → aggregate → compare → flag) → Report shows summary + flagged rows table → User filters, exports, or saves setup

---

## 3+ File Comparison (Inferred Design)

**User has 3 files**: Horizon, Client A, Client B

**Two comparison modes**:

### Mode 1: Compare All to Baseline
```
"Compare Client A and Client B against Horizon as baseline"
↓
Generates TWO reports:
  - Horizon vs Client A (side-by-side metrics)
  - Horizon vs Client B (side-by-side metrics)
↓
User sees both reports sequentially
```

### Mode 2: Compare All Pairs (All-vs-All)
```
"Compare all pairs"
↓
Generates THREE reports:
  - Horizon vs Client A
  - Horizon vs Client B
  - Client A vs Client B
↓
User navigates between reports
```

**Default**: Baseline mode (simpler, cleaner)

---

## Schema Mapping & Configuration (User Fills Out Granularly)

**Users define the comparison rules step-by-step, with agent confirmation at each stage:**

### Step 1: Upload & Parse Files

```
Agent: "Upload two files (Excel or CSV)"
User: [Uploads file A and file B]
Agent: "✓ File A: 3,250 rows, columns detected: ID, Channel, Date, Spend, Impressions, Clicks"
Agent: "✓ File B: 2,980 rows, columns detected: Client_ID, Campaign, Date, Amount, Clicks"
Agent: "Correct? Any sheets I should use instead?"
User: "Yes, looks good"
```

**What happens**:
- Agent auto-detects column headers (scans first 15 rows for the header row)
- Displays row count and column names
- User confirms or picks a different sheet (for multi-sheet workbooks)

### Step 2: Define Match Key (Rows Compared When These Columns Are Equal)

```
Agent: "Which columns identify a matching row? (e.g., ID, or ID + Date)"
User: "ID in File A maps to Client_ID in File B"
Agent: "Got it. Any other key fields? (e.g., Date, Channel)"
User: "No, just ID"
```

**What user specifies**:
- One or more key columns per file (e.g., ID in File A, Client_ID in File B)
- Agent normalizes: case-insensitive, whitespace-trimmed matching
- Rows with matching key values will be compared; mismatches flagged as "Missing" or "Extra"

### Step 3: Define Metrics to Compare (Numeric Columns to Sum & Diff)

```
Agent: "Which columns should I compare?"
User: "Spend and Impressions"
Agent: "I'll look for Spend in both files and Impressions in both files. Correct?"
User: "Yes, but Spend is called 'Amount' in File B"
Agent: "Got it. Spend (File A) vs Amount (File B), and Impressions in both"
```

**What user specifies**:
- Metric name (e.g., "Spend")
- Which column in File A (e.g., "Spend")
- Which column in File B (e.g., "Amount")
- Agent suggests matches automatically if columns have similar names

**Agent validates**:
- Column exists in both files
- Column is numeric (or can be coerced to numeric)
- At least one metric selected

### Step 4: Define Thresholds per Metric (% and/or Units)

```
Agent: "Threshold for Spend? (flag if difference exceeds...)"
User: "5% or $1,000"
Agent: "Got it: flag if Spend differs by more than 5% OR $1,000"
Agent: "Threshold for Impressions?"
User: "10%"
Agent: "Got it: flag if Impressions differs by more than 10%"
```

**What user specifies**:
- Percent threshold (required): e.g., ±5%
- Unit threshold (optional): e.g., ±$1,000
- If both set: flag if EITHER threshold exceeded (OR logic, not AND)

**Validation**:
- Thresholds ≥ 0
- At least one threshold per metric

### Step 5: Apply Optional Row Filters (Before Comparison)

```
Agent: "Any filters before comparing? (e.g., Display channel only, exclude certain dates)"
User: "Filter File A to Display channel only"
Agent: "Which column? Display? Value?"
User: "Channel = Display"
Agent: "Got it. Filtering File A to Display rows. Any other filters?"
User: "No"
```

**What user specifies**:
- Column to filter on (e.g., "Channel")
- Keep or exclude mode
- Which values (e.g., "Display", or "Display + Video")
- Applied per file, before aggregation & comparison

**Validation**:
- Column exists in file
- At least one value selected

### Step 6: Confirm & Run

```
Agent: "Ready to compare?"
Summary:
  - Files: File A (Display only, 2,100 rows) vs File B (all rows, 2,980)
  - Match key: ID
  - Metrics: Spend (A→B) with ±5% or ±$1,000, Impressions (A→B) with ±10%
  - Filters: File A / Channel = Display
User: "Yes, run"
```

**At this point**:
1. Agent loads filtered rows
2. Agent aggregates by match key (summing duplicate IDs per file)
3. Agent compares aggregated rows
4. Agent flags rows exceeding thresholds
5. Agent generates report

---

## Report Format (Complete Output)

**Report contains only flagged rows by default. No "show all rows" option—user focus is on exceptions.**

### Section 1: Summary Stats

```
Comparison: Horizon vs Client A
• Files: Horizon_Q2.xlsx (3,250 rows) ↔ Client_A_Q2.xlsx (2,980 rows)
• After QA checks: Horizon 3,248 rows (2 excluded) ↔ Client A 2,978 rows (2 excluded)
• Aggregated to: 752 unique IDs in Horizon ↔ 741 unique IDs in Client A
• Matched on key: 746 rows (both files)
• Unmatched: 6 in Horizon only, 5 in Client A only
• Flagged issues: 48 rows (above threshold)
```

### Section 2: Metric Totals (Aggregated Across All Rows)

```
Spend:
  Horizon:   $45,230,000
  Client A:  $48,100,000
  Δ:         +$2,870,000 (+6.3%) ⚠ Above threshold (±5% or ±$1,000,000)

Impressions:
  Horizon:   1,230,450
  Client A:  1,298,600
  Δ:         +68,150 (+5.5%) ✓ Within threshold (±10%)
```

### Section 3: Flagged Rows Table (Only ⚠ Mismatch and ✗ Missing/Extra shown)

```
| Match Key | Status | Spend (H) | Spend (CA) | Δ | Δ% |
|-----------|--------|-----------|------------|---|----|
| ID-002, Video | ⚠ Mismatch | $5,000 | $7,500 | +$2,500 | +50.0% |
| ID-003, Display | ✗ Missing | $3,000 | — | — | — |
| ID-456, Social | ✗ Extra | — | $2,200 | — | — |
```

---

## Data Handling (After QA Checks)

**QA Stage (Auto-Cleanup)**:
- **Whitespace anomalies**: Auto-cleaned (leading/trailing spaces removed)
- **Formatting**: Auto-fixed (commas in numbers removed, currency symbols stripped)
- **Date format**: Auto-converted to m/dd/yyyy if parseable
- **Decimal integers**: Auto-truncated (e.g., 1000.5 → 1000)
- **Blank Placement IDs**: Flagged for manual review; excluded from comparison if user proceeds
- **Negative values**: Flagged for manual review; included in comparison if user proceeds (with warning)

**Comparison Stage (Post-QA Data Handling)**:
- **Blank metric cells**: Treated as 0 (Spend, Impressions, Clicks)
- **Non-numeric values in metrics**: Already caught in QA; if any slip through, excluded from totals with warning
- **Duplicate keys**: Summed (if ID=123 appears 3 times, sum all 3 rows' metrics)
- **Case-insensitive matching**: "client_id" matches "Client_ID" (normalized before matching)
- **Trimmed whitespace**: " ID " matches "ID" (trimmed in QA stage, so clean for matching)

---

## Aggregation (Before Comparison)

**When multiple rows share the same match key, sum their metrics**:

```
Input: Three rows with ID=123
  Row 1: ID=123, Spend=$1,000, Impressions=10,000
  Row 2: ID=123, Spend=$500,  Impressions=5,000
  Row 3: ID=123, Spend=$200,  Impressions=2,000

After aggregation:
  ID=123: Spend=$1,700, Impressions=17,000
```

**Process** (happens per file, before any cross-file matching):
1. Group rows by match key (e.g., ID)
2. For each group, sum all metrics (Spend, Impressions, Clicks, Video Completes, etc.)
3. Treat nulls/blanks as 0
4. Return one aggregated row per unique key

**Output**: One aggregated row per unique key per file → ready for cross-file comparison

---

## Comparison Logic (Core Threshold & Status Determination)

### Threshold Evaluation (% OR units, whichever is set)

```
Flag if EITHER condition is true:
  1. Percent difference > user's % threshold, OR
  2. Absolute unit difference > user's unit threshold (if set)

Example: Spend threshold ±5% OR ±$1,000
  
  Scenario A: $100 vs $107
    Δ% = 7%  ← exceeds 5%? YES → FLAG
    
  Scenario B: $1,000,000 vs $1,000,500
    Δ% = 0.05%, Δ$ = $500  ← both under → NOT FLAGGED
    
  Scenario C: $0 vs $500
    Δ% = 100% (special: zero baseline = 100%)  ← exceeds 5%? YES → FLAG
```

**When both % and unit thresholds are set**:
```
Flag if: (Δ% > thresholdPct) OR (Δ$ > thresholdUnits)
This catches:
  • Small % with large absolute swing (0.1% of $1M = $1K → exceeds $500 threshold)
  • Large % with small base (50% of $100 = $50 → exceeds 10% but not $100 threshold)
```

### Row Status Determination

```
IF File A row exists AND File B row does NOT exist:
  Status = "Missing"

ELSE IF File A row does NOT exist AND File B row DOES exist:
  Status = "Extra"

ELSE IF both rows exist:
  IF any metric EXCEEDS its threshold:
    Status = "Mismatch"
  ELSE IF all metrics are within threshold:
    Status = "Match" (NOT shown in flagged table)
```

### Data Handling During Comparison

**Blank cells in metric columns**: Treated as 0

**Non-numeric values**: Excluded from totals; flagged with examples (e.g., "N/A" in Spend)

**Case-insensitive, whitespace-trimmed matching**: "CLIENT_ID" matches "client_id"

---

## Dynamic Filters (Post-Report)

* Filter by key value: "Show only Client A records"
* Hide zeros: Hide rows where all metrics are 0
* Combined: Use both filters together (AND logic)

---

## Workflow Examples

### Example 1: Two Files (with QA + User Control)
```
TIME: 0:00
User: "Compare Q2 Horizon vs Client reports"

TIME: 0:30
Agent: "Upload or paste Sharepoint URL"
User: [pastes Sharepoint link]
Agent: [Downloads from Sharepoint] 
Agent: "Files ready. Define match key?"
User: "ID"
Agent: "Which metrics?"
User: "Spend, Impressions"
Agent: "Any filters?"
User: "No"
Agent: "Running QA checks..."

TIME: 0:45
Agent: [QA results appear]
"⚠ Found 3 issues:
  ✓ Auto-fixable (2): Whitespace in files A & B
  ⚠ Needs review (1): Blank Placement ID in row 42 of file B

What should I do?
[✓ Auto-fix & proceed] [⚠ Exclude problem rows] [✏️ Edit files] [▶️ Proceed anyway]"

User: "Auto-fix & proceed"

TIME: 1:00
Agent: [Report appears]
Agent: "✓ Complete. 46 rows flagged. (1 row excluded due to blank ID)"

[Shows summary + table]

[Data Quality Note:
"✓ Auto-fixed: 2 whitespace issues
⚠ Excluded: 1 row (blank Placement ID)"]

User: "Show only mismatches"
[Table filters]

User: "Export to Excel"
Agent: [Downloads styled spreadsheet with QA notes]
```

### Example 2: Three Files (All-vs-All)
```
User: "Compare Horizon, Client A, Client B (all pairs)"

Agent: "Comparing all 3 pairs..."
[Generates 3 reports in sequence]
Agent: "Report 1/3: Horizon vs Client A (46 flagged)"
[Shows table, user can filter]

User: "Next"
Agent: "Report 2/3: Horizon vs Client B (28 flagged)"

User: "Next"
Agent: "Report 3/3: Client A vs Client B (120 flagged)"

User: "Go back to Report 1"
[Jumps to first report]
```

---

## Technical Defaults

| Parameter | Value |
|-----------|-------|
| File timeout | 30 seconds per file (download + parse) |
| Web Worker for parsing | Yes, for files > 50K rows (no UI freeze) |
| Session duration | 1 hour idle timeout; clear after use |
| File retention | Delete uploaded files after 24 hours |
| Memory Bank limit | 1900 chars per user (same as Hour Hero) |
| Concurrent comparisons per user | 1 at a time (queue others) |
| Error retry logic | 1 retry on network timeout; then fail |

---

## Export Formats

### CSV Export

```
Filename: DataMatch_QA_Results_[Date].csv
```

Includes: Match Key, Status, For each metric: [Metric] (File A), [Metric] (File B), Δ, Δ%
Rows: Flagged rows only (respects UI filters)

### Excel Export

```
Filename: DataMatch_QA_Results_[Date].xlsx
```

Sheet 1: "Summary" → Metadata, row counts, metric totals, pass/fail vs threshold
Sheet 2: "Flagged Rows" → Flagged rows with color-coding (green=within, yellow=exceed, gray=blank)
Sheet 3: "All Rows" (optional) → All rows including matches, for reference

---

## Auto-Filtration & Data Quality Checks

**On file ingestion, automatically run** (show results; never block):

1. Date Format: Auto-fixable if parseable
2. Numeric Fields: Metric columns must be integers or blank (auto-fixable if decimal)
3. Negative Values: Flagged for review
4. Formatting: No leading/trailing whitespace, no commas in numbers (auto-fixable)

**User options**:

* ✓ Auto-fix: Accept all auto-fixes and proceed
* ⚠ Exclude: Remove rows with unfixable issues
* ✏️ Edit: Return to file, correct, re-upload
* ▶️ Proceed as-is: Ignore warnings (issues excluded from totals)

**Comparison always runs** (never blocking) — user has transparency + control.

---

## Edge Cases (From HTML Tool)

**Handled as-is from existing tool**:
- Multi-sheet workbooks: User picks sheet
- Duplicate headers: Auto-numbered (ID, ID_2, ID_3)
- Empty rows: Skipped
- Mixed data types: Non-numeric values flagged & excluded
- Large files: Web Worker prevents UI freeze
- Corrupt files: Error message + guidance

**Handled via QA checks**:
- Date format inconsistencies: Auto-fixed if parseable
- Whitespace anomalies: Auto-cleaned
- Decimal integers: Auto-truncated
- Negative values: Flagged for user review

**NOT handled** (out of scope):
- Auto-correct source data
- Create new metrics
- Modify source files

---

## Saving & Reusing Mappings

**Memory Bank**: Stores per-user column mappings, thresholds, filters (1900 char limit)

**Next time user uploads files with same names** → Agent auto-applies saved setup → Column matching suggestions shown if columns renamed

---

## Validation & Error Handling

**Auto-validates on parse**:
- ✓ Column exists in file
- ✓ Key column not empty
- ✓ Metric column is numeric (or coercible)
- ✓ At least 2 columns detected

**User-facing errors** (with recovery):
```
Error: "Column 'Spend' not found in File A"
Recovery: "Available columns: [list]. Pick one."

Error: "Metric column contains non-numeric values"
Recovery: "Non-numeric found: 'N/A', '—'. Excluded from totals. Continue?"
```

---

## Architecture Summary

```
Conversation Agent (Gemini)
    ↓
Pipeline (3-stage Python engine)
  ├─ Load: Parse files, detect headers
  ├─ Aggregate: Group by key, sum metrics per file
  └─ Compare: Calculate deltas, flag, render report
    ↓
Memory Bank (save/load mappings)
    ↓
Export (CSV or Excel)
```

**No LLM decisions during comparison.** Gemini handles conversation; Python does all data logic deterministically.
