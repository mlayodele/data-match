"""Comparison engine for running schema-driven file analysis.

APPROACH: .0 Normalization for ID Matching
---
When pandas reads CSV, numeric columns with NaN/blanks are inferred as float64.
This causes:
- "435852651" (string-loaded) ≠ "435852651.0" (float-loaded)
- Match fails even though they're the same ID

SOLUTION: Normalize all numeric-looking IDs to include .0
- "435852651" → "435852651.0"
- "435852651.0" → "435852651.0" (already has it)
- Result: both files match on "435852651.0"
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

import numpy as np
import pandas as pd
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)


def _convert_numpy_types(obj: Any) -> Any:
    """Recursively convert numpy types to native Python types."""
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: _convert_numpy_types(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_convert_numpy_types(item) for item in obj]
    return obj


def run_comparison(
    file_a_bytes: bytes,
    file_b_bytes: bytes,
    header_row_a: int,
    header_row_b: int,
    match_keys: list[dict[str, str]],
    metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run comparison pipeline: load → aggregate → compare → flag.

    Args:
        file_a_bytes: CSV file bytes for File A
        file_b_bytes: CSV file bytes for File B
        header_row_a: Header row number (1-indexed) for File A
        header_row_b: Header row number (1-indexed) for File B
        match_keys: List of {file_a_col, file_b_col} dicts
        metrics: List of {name, file_a_col, file_b_col, threshold_pct} dicts

    Returns:
        Dict with summary_stats, metric_totals, flagged_rows
    """
    with _tracer.start_as_current_span("run_comparison") as span:
        try:
            # STAGE 1: LOAD
            with _tracer.start_as_current_span("load_files") as load_span:
                match_key_cols_a = [mk["file_a_col"] for mk in match_keys]
                match_key_cols_b = [mk["file_b_col"] for mk in match_keys]

                load_span.set_attribute("match_key_cols_a", match_key_cols_a)
                load_span.set_attribute("match_key_cols_b", match_key_cols_b)

                df_a = pd.read_csv(BytesIO(file_a_bytes), header=header_row_a - 1)
                df_b = pd.read_csv(BytesIO(file_b_bytes), header=header_row_b - 1)

                load_span.set_attribute("file_a_rows", len(df_a))
                load_span.set_attribute("file_b_rows", len(df_b))
                load_span.set_attribute("file_a_cols", len(df_a.columns))
                load_span.set_attribute("file_b_cols", len(df_b.columns))

            # Extract column names for match keys and metrics
            match_key_cols_a = [mk["file_a_col"] for mk in match_keys]
            match_key_cols_b = [mk["file_b_col"] for mk in match_keys]
            metric_cols_a = {m["name"]: m["file_a_col"] for m in metrics}
            metric_cols_b = {m["name"]: m["file_b_col"] for m in metrics}

            with _tracer.start_as_current_span("aggregate") as agg_span:
                # Group File A by match keys, sum metrics
                agg_a = _aggregate_file(
                    df_a, match_key_cols_a, metric_cols_a
                )
                # Group File B by match keys, sum metrics
                agg_b = _aggregate_file(
                    df_b, match_key_cols_b, metric_cols_b
                )

                agg_span.set_attribute("agg_a_groups", len(agg_a))
                agg_span.set_attribute("agg_b_groups", len(agg_b))

            # STAGE 3: COMPARE & FLAG
            with _tracer.start_as_current_span("compare") as cmp_span:
                comparison = _compare_aggregated(
                    agg_a, agg_b, metrics
                )

                cmp_span.set_attribute("matched_pairs", comparison["summary_stats"]["matched_pairs"])
                cmp_span.set_attribute("missing_in_a", comparison["summary_stats"]["missing_in_a"])
                cmp_span.set_attribute("missing_in_b", comparison["summary_stats"]["missing_in_b"])
                cmp_span.set_attribute("flagged_count", comparison["summary_stats"]["flagged_count"])

            span.set_attribute("status", "success")

            result = _convert_numpy_types(comparison)
            return result

        except Exception as e:
            span.set_attribute("status", "error")
            span.record_exception(e)
            raise


def _aggregate_file(
    df: pd.DataFrame,
    match_key_cols: list[str],
    metric_cols: dict[str, str],
) -> pd.DataFrame:
    """Group rows by match key, sum metric columns."""
    with _tracer.start_as_current_span("aggregate_file") as span:
        try:
            # Remove rows where ALL columns are NaN (blank rows from export padding)
            df = df.dropna(how='all')
            span.set_attribute("rows_after_dropna", len(df))

            # Create match key tuple column with normalization for numeric IDs
            df_work = df.copy()

            for col in match_key_cols:
                # Normalize match key values for consistent matching
                df_work[col] = df_work[col].fillna('MISSING')  # Fill NaN with MISSING
                df_work[col] = df_work[col].astype(str).str.strip()  # Convert to string, strip whitespace

                # For numeric-looking values (all digits), add .0 for consistent matching
                # This handles the case where float-loaded values have .0 and string-loaded don't
                is_numeric = df_work[col].str.match(r'^\d+$', na=False)
                df_work.loc[is_numeric, col] = df_work.loc[is_numeric, col] + '.0'

                # Replace any 'nan' strings
                df_work[col] = df_work[col].replace('nan', 'MISSING')

                span.set_attribute(f"col_{col}_numeric_ids_normalized", int(is_numeric.sum()))

            if len(match_key_cols) == 1:
                df["__match_key"] = df_work[match_key_cols[0]].astype(str)
            else:
                # Join multiple key columns with pipe separator
                # Ensure ALL values are strings before joining (critical for float prevention)
                key_parts = []
                for col in match_key_cols:
                    key_parts.append(df_work[col].astype(str))
                df["__match_key"] = pd.concat(key_parts, axis=1).agg("|".join, axis=1)

            # Group by match key, sum metrics
            agg_cols = {v: "sum" for v in metric_cols.values()}
            aggregated = df.groupby("__match_key", as_index=False)[list(agg_cols.keys())].sum()

            # Rename back to metric names
            metric_rename = {v: k for k, v in metric_cols.items()}
            aggregated.rename(columns=metric_rename, inplace=True)

            # Add match key columns
            aggregated["__match_key_orig"] = aggregated["__match_key"]

            span.set_attribute("groups", len(aggregated))
            return aggregated

        except Exception as e:
            span.record_exception(e)
            raise


def _compare_aggregated(
    agg_a: pd.DataFrame,
    agg_b: pd.DataFrame,
    metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare aggregated files, flag rows exceeding thresholds."""
    with _tracer.start_as_current_span("compare_aggregated") as span:
        try:
            flagged_rows = []
            matched_pairs = 0
            missing_in_a = 0
            missing_in_b = 0

            # Get metric names
            metric_names = [m["name"] for m in metrics]
            threshold_map = {m["name"]: m.get("threshold_pct", 0) for m in metrics}

            # Find all unique match keys
            all_keys = set(agg_a["__match_key"].values) | set(agg_b["__match_key"].values)

            for key in all_keys:
                row_a = agg_a[agg_a["__match_key"] == key]
                row_b = agg_b[agg_b["__match_key"] == key]

                if len(row_a) == 0:
                    # Missing in A (extra in B)
                    missing_in_b += 1
                    values_b = {m: row_b[m].values[0] if len(row_b) > 0 else 0 for m in metric_names}
                    flagged_rows.append({
                        "match_key": key,
                        "status": "Extra",
                        "file_a_metrics": {m: None for m in metric_names},
                        "file_b_metrics": values_b,
                        "deltas": {m: None for m in metric_names},
                        "delta_pcts": {m: None for m in metric_names},
                    })
                elif len(row_b) == 0:
                    # Missing in B
                    missing_in_a += 1
                    values_a = {m: row_a[m].values[0] if len(row_a) > 0 else 0 for m in metric_names}
                    flagged_rows.append({
                        "match_key": key,
                        "status": "Missing",
                        "file_a_metrics": values_a,
                        "file_b_metrics": {m: None for m in metric_names},
                        "deltas": {m: None for m in metric_names},
                        "delta_pcts": {m: None for m in metric_names},
                    })
                else:
                    # Both exist - compare metrics
                    matched_pairs += 1
                    values_a = {m: row_a[m].values[0] for m in metric_names}
                    values_b = {m: row_b[m].values[0] for m in metric_names}

                    is_mismatch = False
                    deltas = {}
                    delta_pcts = {}

                    for metric_name in metric_names:
                        val_a = values_a[metric_name]
                        val_b = values_b[metric_name]

                        delta = val_b - val_a
                        deltas[metric_name] = delta

                        # Calculate % diff (handle zero baseline)
                        if val_a == 0:
                            delta_pct = 100.0 if delta != 0 else 0.0
                        else:
                            delta_pct = (delta / val_a) * 100
                        delta_pcts[metric_name] = delta_pct

                        # Check threshold
                        threshold = threshold_map.get(metric_name, 0)
                        if abs(delta_pct) > threshold:
                            is_mismatch = True

                    if is_mismatch:
                        flagged_rows.append({
                            "match_key": key,
                            "status": "Mismatch",
                            "file_a_metrics": values_a,
                            "file_b_metrics": values_b,
                            "deltas": deltas,
                            "delta_pcts": delta_pcts,
                        })

            # Calculate metric totals
            metric_totals = {}
            for metric_name in metric_names:
                total_a = agg_a[metric_name].sum() if metric_name in agg_a.columns else 0
                total_b = agg_b[metric_name].sum() if metric_name in agg_b.columns else 0
                delta = total_b - total_a
                delta_pct = (delta / total_a * 100) if total_a != 0 else (100.0 if delta != 0 else 0.0)

                metric_totals[metric_name] = {
                    "file_a": total_a,
                    "file_b": total_b,
                    "delta": delta,
                    "delta_pct": delta_pct,
                }

            span.set_attribute("matched_pairs", matched_pairs)
            span.set_attribute("missing_in_a", missing_in_a)
            span.set_attribute("missing_in_b", missing_in_b)
            span.set_attribute("flagged", len(flagged_rows))

            return {
                "summary_stats": {
                    "matched_pairs": matched_pairs,
                    "missing_in_a": missing_in_a,
                    "missing_in_b": missing_in_b,
                    "flagged_count": len(flagged_rows),
                },
                "metric_totals": metric_totals,
                "flagged_rows": flagged_rows,
            }

        except Exception as e:
            span.record_exception(e)
            raise
