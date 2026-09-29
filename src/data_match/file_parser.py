"""Parse Excel/CSV and detect columns."""
from typing import List, Tuple
import pandas as pd
from io import BytesIO


def parse_file(file_bytes: bytes, filename: str, header_row: int = 0) -> Tuple[int, List[str]]:
    """Parse file and return (row_count, column_names).

    Args:
        file_bytes: File content as bytes
        filename: Name of the file
        header_row: 0-indexed row number where headers start (default: 0 = first row)

    Returns:
        (total_rows, list_of_column_names)
    """
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(BytesIO(file_bytes), encoding='utf-8', on_bad_lines='skip', header=header_row)
    elif filename.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(file_bytes, sheet_name=0, header=header_row)
    else:
        raise ValueError(f"Unsupported format: {filename}")

    # Get column names from the specified header row
    headers = df.columns.tolist()
    headers = [str(h).strip() for h in headers if str(h).strip() != ""]

    # Row count is the number of data rows (excluding header)
    row_count = len(df)

    return row_count, headers


def get_sheet_names(file_bytes: bytes, filename: str) -> List[str]:
    """Get sheet names from Excel file."""
    if not filename.lower().endswith((".xlsx", ".xls")):
        return [filename]
    xls = pd.ExcelFile(file_bytes)
    return xls.sheet_names


def get_data_preview(file_bytes: bytes, filename: str, start_row: int = 0, num_rows: int = 7) -> str:
    """Get a markdown table preview of data rows with row numbers.

    Args:
        file_bytes: File content as bytes
        filename: Name of the file
        start_row: 0-indexed row to start preview from
        num_rows: Number of rows to display (default: 7)

    Returns:
        Markdown table with row numbers
    """
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(BytesIO(file_bytes), encoding='utf-8', on_bad_lines='skip', header=None)
    elif filename.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(file_bytes, sheet_name=0, header=None)
    else:
        raise ValueError(f"Unsupported format: {filename}")

    # Get rows to display
    end_row = min(start_row + num_rows, len(df))
    preview_df = df.iloc[start_row:end_row].copy()

    # Add row numbers (1-indexed for user display)
    preview_df.insert(0, 'Row #', range(start_row + 1, end_row + 1))

    # Convert to markdown table
    markdown = preview_df.to_markdown(index=False)
    return markdown if markdown else "No data available"
