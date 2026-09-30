# Artifact Service Behavior Findings

## Discovered Pattern

### Scenario A: Works
1. User: "read the first 10 rows from each file"
2. Agent: "I can't directly read the first 10 rows"
3. Agent: "What row number contains your ACTUAL column headers?"
4. User: "31"
5. Agent: Returns row content, row count, detected columns ✓
6. Workflow continues successfully to Step 2

### Scenario B: Fails
1. User uploads files
2. Agent: "What row number contains your ACTUAL column headers?"
3. User: "31"
4. Agent: Error "could not read the file" ✗
5. Agent: "It seems the files I was working with are no longer available"

## Observable Difference
- Scenario A: Two agent messages between upload and header-row request
- Scenario B: One agent message between upload and header-row request
- Scenario A: File reads succeed
- Scenario B: File reads fail, files reported as unavailable

## Variables
- Both scenarios use the same files
- Both scenarios ask for the same header row number
- Both scenarios use the same tools (parse_with_header, inspect_csv_row)
- The only difference is the number and content of intermediate agent messages
