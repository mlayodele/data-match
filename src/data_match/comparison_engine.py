"""Comparison engine for running schema-driven file analysis.

PROBLEM FIXED: HX file has 7,975 rows with null Date/Placement ID (rows 2085-10060).
These are leftover data from earlier weeks that shouldn't participate in matching.
Filling nulls with 'MISSING' was creating false "MISSING|MISSING" match key aggregations.

SOLUTION:
1. Remove rows with ANY null match key columns before processing (dropna(subset=match_key_cols))
2. This prevents false "MISSING|MISSING" match key aggregations
3. For remaining rows: fill any remaining NaN with 'MISSING', then convert to string
4. Add match_key_types parameter to enable explicit type handling (string, date)
5. Normalize dates to ISO format and keep IDs as strings consistently
"""
from __future__ import annotations

import itertools
from io import BytesIO
from typing import Any

import numpy as np
import pandas as pd
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

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
    match_key_types: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run comparison pipeline: load → aggregate → compare → flag.

    Args:
        file_a_bytes: CSV file bytes for File A
        file_b_bytes: CSV file bytes for File B
        header_row_a: Header row number (1-indexed) for File A
        header_row_b: Header row number (1-indexed) for File B
        match_keys: List of {file_a_col, file_b_col} dicts
        metrics: List of {name, file_a_col, file_b_col, threshold_pct} dicts
        match_key_types: Dict mapping match key names to types (string, date, etc.)

    Returns:
        Dict with summary_stats, metric_totals, flagged_rows
    """
    with _tracer.start_as_current_span("run_comparison") as span:
        try:
            # STAGE 1: LOAD with match key columns protected from pandas inference
            with _tracer.start_as_current_span("load_files") as load_span:
                # Extract match key column names from match_keys parameter
                # This is bulletproof: doesn't depend on agent passing types
                match_key_cols_a = [mk["file_a_col"] for mk in match_keys]
                match_key_cols_b = [mk["file_b_col"] for mk in match_keys]

                # CRITICAL: Always specify dtype=str for match key columns
                # This prevents pandas from inferring float64 due to NaN values in blank rows
                # All other columns (metrics, etc.) are left for pandas to infer normally
                # (needed for aggregation operations like sum)
                dtype_a = {col: str for col in match_key_cols_a}
                dtype_b = {col: str for col in match_key_cols_b}

                load_span.set_attribute("match_key_cols_a", match_key_cols_a)
                load_span.set_attribute("match_key_cols_b", match_key_cols_b)
                load_span.set_attribute("dtype_a", dtype_a)
                load_span.set_attribute("dtype_b", dtype_b)

                df_a = pd.read_csv(BytesIO(file_a_bytes), header=header_row_a - 1, dtype=dtype_a)
                df_b = pd.read_csv(BytesIO(file_b_bytes), header=header_row_b - 1, dtype=dtype_b)

                load_span.set_attribute("file_a_rows", len(df_a))
                load_span.set_attribute("file_b_rows", len(df_b))
                load_span.set_attribute("file_a_cols", len(df_a.columns))
                load_span.set_attribute("file_b_cols", len(df_b.columns))

            # Extract column names for match keys and metrics
            match_key_cols_a = [mk["file_a_col"] for mk in match_keys]
            match_key_cols_b = [mk["file_b_col"] for mk in match_keys]
            metric_cols_a = {m["name"]: m["file_a_col"] for m in metrics}
            metric_cols_b = {m["name"]: m["file_b_col"] for m in metrics}

            # Match key types are confirmed by user in STEP 2.5 - no inference needed
            # If not provided, default all match keys to 'string'
            if not match_key_types:
                match_key_types = {col: 'string' for col in match_key_cols_a}

            with _tracer.start_as_current_span("use_confirmed_types") as span:
                span.set_attribute("match_key_types_confirmed", match_key_types)

            with _tracer.start_as_current_span("aggregate") as agg_span:
                # Group File A by match keys, sum metrics (using consistent types)
                agg_a = _aggregate_file(
                    df_a, match_key_cols_a, metric_cols_a, match_key_types
                )
                # Group File B by match keys, sum metrics (using SAME types as File A)
                agg_b = _aggregate_file(
                    df_b, match_key_cols_b, metric_cols_b, match_key_types
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

            # Add debug info to results
            result = _convert_numpy_types(comparison)
            result["_debug"] = {
                "match_key_types_passed_by_agent": bool(match_key_types),
                "match_key_types_applied": match_key_types,
                "file_a_agg_keys_sample": agg_a["__match_key"].head(5).tolist() if len(agg_a) > 0 else [],
                "file_b_agg_keys_sample": agg_b["__match_key"].head(5).tolist() if len(agg_b) > 0 else [],
                "file_a_unique_keys": len(agg_a),
                "file_b_unique_keys": len(agg_b),
                "note": "Types applied consistently to both files (inferred from File A if not provided)",
            }
            return result

        except Exception as e:
            span.set_attribute("status", "error")
            span.record_exception(e)
            raise


def _aggregate_file(
    df: pd.DataFrame,
    match_key_cols: list[str],
    metric_cols: dict[str, str],
    match_key_types: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Group rows by match key, sum metric columns."""
    with _tracer.start_as_current_span("aggregate_file") as span:
        try:
            # Remove rows where ANY match key column is NaN (can't match without keys)
            rows_before = len(df)
            df = df.dropna(subset=match_key_cols)
            rows_after = len(df)
            span.set_attribute("rows_before_dropna", rows_before)
            span.set_attribute("rows_after_dropna", rows_after)
            span.set_attribute("rows_removed_with_null_keys", rows_before - rows_after)

            # Create match key tuple column with type-driven conversion
            df_work = df.copy()

            if match_key_types is None:
                match_key_types = {}
            span.set_attribute("match_key_types_provided", bool(match_key_types))
            span.set_attribute("match_key_types_value", match_key_types)

            for col in match_key_cols:
                # Use confirmed type from match_key_types (user confirmed in STEP 2.5)
                col_type = match_key_types.get(col, 'string').lower()
                span.set_attribute(f"col_{col}_type", col_type)

                # Match key columns already loaded as strings (dtype=str during CSV load)
                # Just handle NaN/missing values
                df_work[col] = df_work[col].fillna('MISSING')  # Fill NaN with MISSING
                df_work[col] = df_work[col].astype(str)        # Ensure all are strings
                df_work[col] = df_work[col].replace('nan', 'MISSING')  # Replace 'nan' strings

                # Auto-detect dates: if type is 'date' OR column name looks like a date field
                should_parse_date = (col_type == 'date' or
                                   any(date_word in col.lower() for date_word in ['date', 'time', 'day', 'month', 'year']))

                if should_parse_date:
                    # Parse as date and normalize to ISO format
                    try:
                        parsed = pd.to_datetime(df_work[col], errors='coerce')
                        valid_mask = parsed.notna()
                        df_work.loc[valid_mask, col] = parsed[valid_mask].dt.strftime("%Y-%m-%d")
                        span.set_attribute(f"col_{col}_dates_normalized", int(valid_mask.sum()))
                    except:
                        span.set_attribute(f"col_{col}_date_parse_failed", True)
                else:
                    # For ID columns: normalize numeric values to include .0
                    # This handles float-loaded IDs ("435852651.0") matching string-loaded IDs ("435852651")
                    is_numeric = df_work[col].str.match(r'^\d+$', na=False)
                    df_work.loc[is_numeric, col] = df_work.loc[is_numeric, col] + '.0'
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
            threshold_pct_map = {m["name"]: m.get("threshold_pct", 0) for m in metrics}
            # Absolute/unit threshold (e.g. "$1,000"), optional per metric.
            # None means "not set" -- distinct from 0, which would flag any
            # nonzero delta.
            threshold_units_map = {m["name"]: m.get("threshold_units") for m in metrics}

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

                        threshold_pct = threshold_pct_map.get(metric_name, 0)
                        threshold_units = threshold_units_map.get(metric_name)

                        if val_a == 0:
                            # Percentage change from a zero baseline is
                            # mathematically undefined, not just inconvenient --
                            # don't fabricate a number for it. Fall back to the
                            # absolute/unit threshold when one is configured,
                            # since it's still meaningful (e.g. "$0 vs $50,000"
                            # is worth flagging, "$0 vs $0.02" is not).
                            delta_pct = None
                            if threshold_units is not None:
                                exceeds = abs(delta) > threshold_units
                            else:
                                # No unit threshold configured: preserve prior
                                # behavior (flag any nonzero delta) since there's
                                # no dollar floor to fall back on.
                                exceeds = delta != 0
                        else:
                            delta_pct = (delta / val_a) * 100
                            exceeds_pct = abs(delta_pct) > threshold_pct
                            exceeds_units = (
                                threshold_units is not None
                                and abs(delta) > threshold_units
                            )
                            exceeds = exceeds_pct or exceeds_units

                        delta_pcts[metric_name] = delta_pct

                        if exceeds:
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


def run_multi_file_comparison(
    files: list[dict[str, Any]],
    match_keys: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    mode: str = "baseline",
    baseline_file: str | None = None,
) -> dict[str, Any]:
    """Compare 2+ files pairwise: aggregate each file once, then compare pairs.

    Args:
        files: List of {name, bytes, header_row} per file.
        match_keys: List of {columns: {file_name: col_name}, type: "string"|"date"}.
            Each file may use a different column name for the same logical key
            (e.g. "ID" in File A, "Client_ID" in File B).
        metrics: List of {name, columns: {file_name: col_name}, threshold_pct}.
        mode: "baseline" (compare every other file against `baseline_file`) or
            "all_pairs" (compare every combination of two files).
        baseline_file: Required when mode="baseline" — must match one of
            files[i]["name"].

    Returns:
        Dict with mode, baseline_file, file_names, pairs_compared, and a
        `results` list — one run_comparison-shaped result per pair, each
        tagged with file_a/file_b.
    """
    with _tracer.start_as_current_span("run_multi_file_comparison") as span:
        try:
            file_names = [f["name"] for f in files]
            span.set_attribute("file_count", len(files))
            span.set_attribute("file_names", file_names)
            span.set_attribute("mode", mode)

            if len(files) < 2:
                raise ValueError("At least 2 files are required for comparison")
            if mode == "baseline":
                if not baseline_file:
                    raise ValueError("baseline_file is required when mode='baseline'")
                if baseline_file not in file_names:
                    raise ValueError(f"baseline_file '{baseline_file}' not found in files")
            elif mode != "all_pairs":
                raise ValueError(f"mode must be 'baseline' or 'all_pairs', got '{mode}'")

            # Aggregate each file exactly once, using that file's own column
            # names for the match keys / metrics (column names may differ
            # per file even though they represent the same logical field).
            aggregated: dict[str, pd.DataFrame] = {}
            for f in files:
                name = f["name"]
                header_row = f["header_row"]

                match_key_cols = [mk["columns"][name] for mk in match_keys]
                metric_cols = {m["name"]: m["columns"][name] for m in metrics}
                match_key_types = {
                    mk["columns"][name]: mk.get("type", "string") for mk in match_keys
                }

                dtype_map = {col: str for col in match_key_cols}
                with _tracer.start_as_current_span("load_file") as load_span:
                    load_span.set_attribute("file_name", name)
                    df = pd.read_csv(
                        BytesIO(f["bytes"]), header=header_row - 1, dtype=dtype_map
                    )
                    load_span.set_attribute("rows", len(df))

                aggregated[name] = _aggregate_file(
                    df, match_key_cols, metric_cols, match_key_types
                )

            if mode == "all_pairs":
                pairs = list(itertools.combinations(file_names, 2))
            else:
                pairs = [(baseline_file, name) for name in file_names if name != baseline_file]

            span.set_attribute("pairs_count", len(pairs))

            results = []
            for file_a, file_b in pairs:
                with _tracer.start_as_current_span("compare_pair") as pair_span:
                    pair_span.set_attribute("file_a", file_a)
                    pair_span.set_attribute("file_b", file_b)
                    comparison = _compare_aggregated(
                        aggregated[file_a], aggregated[file_b], metrics
                    )
                    pair_span.set_attribute(
                        "flagged_count", comparison["summary_stats"]["flagged_count"]
                    )
                results.append({
                    "file_a": file_a,
                    "file_b": file_b,
                    **_convert_numpy_types(comparison),
                })

            span.set_status(Status(StatusCode.OK))
            return {
                "mode": mode,
                "baseline_file": baseline_file,
                "file_names": file_names,
                "pairs_compared": [[a, b] for a, b in pairs],
                "results": results,
            }

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise
