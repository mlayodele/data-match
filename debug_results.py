"""Helper to format and display comparison analysis results with debug info."""


def format_comparison_results(results: dict) -> str:
    """Format comparison results with debug info to verify type conversion.

    Usage:
        results = <agent response from run_comparison_analysis>
        print(format_comparison_results(results))
    """

    output = []
    output.append("=" * 80)
    output.append("COMPARISON ANALYSIS RESULTS")
    output.append("=" * 80)

    # Summary stats
    if "summary_stats" in results:
        stats = results["summary_stats"]
        output.append("\nSummary Statistics:")
        output.append(f"  • Matched Pairs: {stats.get('matched_pairs', 0)}")
        output.append(f"  • Missing in File A: {stats.get('missing_in_a', 0)}")
        output.append(f"  • Missing in File B: {stats.get('missing_in_b', 0)}")
        output.append(f"  • Total Flagged Rows: {stats.get('flagged_count', 0)}")

    # Metric totals
    if "metric_totals" in results:
        output.append("\nMetric Totals:")
        for metric_name, values in results["metric_totals"].items():
            output.append(f"\n  {metric_name}:")
            output.append(f"    • File A Total: {values.get('file_a', 0)}")
            output.append(f"    • File B Total: {values.get('file_b', 0)}")
            output.append(f"    • Difference: {values.get('delta', 0):.2f}")
            output.append(f"    • Percentage Difference: {values.get('delta_pct', 0):.2f}%")

    # DEBUG: Type inference and key samples
    output.append("\n" + "=" * 80)
    output.append("DEBUG: Type Inference & Match Key Samples")
    output.append("=" * 80)

    if "_debug" in results:
        debug = results["_debug"]

        output.append(f"\nTypes Passed by Agent: {debug.get('match_key_types_passed_by_agent', False)}")
        output.append(f"Types Applied: {debug.get('match_key_types_applied', {})}")
        output.append(f"\nNote: {debug.get('note', 'N/A')}")

        output.append(f"\nFile A Unique Keys: {debug.get('file_a_unique_keys', 0)}")
        output.append("File A Sample Keys (first 5):")
        for key in debug.get('file_a_agg_keys_sample', []):
            output.append(f"  • {key}")

        output.append(f"\nFile B Unique Keys: {debug.get('file_b_unique_keys', 0)}")
        output.append("File B Sample Keys (first 5):")
        for key in debug.get('file_b_agg_keys_sample', []):
            output.append(f"  • {key}")

        # Check if types are being applied correctly
        keys_a = debug.get('file_a_agg_keys_sample', [])
        keys_b = debug.get('file_b_agg_keys_sample', [])

        output.append("\n" + "-" * 80)
        output.append("TYPE CONVERSION CHECK:")
        output.append("-" * 80)

        # Check for float artifacts (.0)
        float_keys_a = [k for k in keys_a if '.0|' in k or k.endswith('.0')]
        float_keys_b = [k for k in keys_b if '.0|' in k or k.endswith('.0')]

        if float_keys_a or float_keys_b:
            output.append("⚠️  WARNING: Float artifacts (.0) detected in match keys!")
            output.append(f"   File A: {len(float_keys_a)} keys with .0")
            output.append(f"   File B: {len(float_keys_b)} keys with .0")
            output.append("   → Type conversion may not be working correctly")
        else:
            output.append("✓ GOOD: No float artifacts (.0) in match keys")
            output.append("  → Types are being converted to strings correctly")

        # Check for date format consistency
        date_format_ok = all('|' in k for k in keys_a + keys_b)
        if date_format_ok and len(keys_a) > 0:
            output.append("✓ GOOD: Match keys have pipe-separated format (Date|ID)")
        else:
            output.append("⚠️  WARNING: Match keys don't have expected format")

    # Flagged rows (sample)
    if "flagged_rows" in results and results["flagged_rows"]:
        flagged = results["flagged_rows"][:10]  # First 10
        total_flagged = len(results["flagged_rows"])

        output.append("\n" + "=" * 80)
        output.append(f"Flagged Rows (showing first {len(flagged)} of {total_flagged} total):")
        output.append("=" * 80)

        for row in flagged:
            output.append(f"\n  Match Key: {row.get('match_key', 'N/A')}")
            output.append(f"  Status: {row.get('status', 'N/A')}")
            if row.get('file_a_metrics'):
                for metric, val in row['file_a_metrics'].items():
                    output.append(f"    File A {metric}: {val}")
            if row.get('file_b_metrics'):
                for metric, val in row['file_b_metrics'].items():
                    output.append(f"    File B {metric}: {val}")

    output.append("\n" + "=" * 80)
    return "\n".join(output)
