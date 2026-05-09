"""
Eval dashboard: visualize eval history from eval_history.jsonl.

Run: streamlit run backend/evals/dashboard.py
"""

from __future__ import annotations

import json
import os

import altair as alt
import pandas as pd
import streamlit as st

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "output", "eval_history.jsonl")


@st.cache_data(ttl=10)
def load_history() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load eval history, returning (per-property results, run summaries)."""
    if not os.path.exists(HISTORY_PATH):
        return pd.DataFrame(), pd.DataFrame()

    records = []
    summaries = []
    with open(HISTORY_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("type") == "summary":
                summaries.append(row)
            else:
                records.append(row)

    return pd.DataFrame(records), pd.DataFrame(summaries)


def main() -> None:
    st.set_page_config(page_title="CloudNimbus Evals", layout="wide")
    st.title("CloudNimbus Eval Dashboard")

    results_df, summary_df = load_history()

    if summary_df.empty:
        st.warning("No eval history found. Run `just eval-gis` or `just eval` to generate data.")
        return

    # --- Error trend over time ---
    st.header("Error Trend")
    error_chart = (
        alt.Chart(summary_df)
        .mark_line(point=True)
        .encode(
            x=alt.X("timestamp:T", title="Run"),
            y=alt.Y("avg_error_pct:Q", title="Avg Error %", scale=alt.Scale(zero=True)),
            tooltip=["run_id", "git_sha", "notes", "avg_error_pct", "mode"],
        )
        .properties(height=300)
    )
    st.altair_chart(error_chart, use_container_width=True)

    # --- Pitch accuracy trend ---
    st.header("Pitch Accuracy Trend")
    pitch_chart = (
        alt.Chart(summary_df)
        .mark_line(point=True, color="green")
        .encode(
            x=alt.X("timestamp:T", title="Run"),
            y=alt.Y("pitch_accuracy:Q", title="Pitch Accuracy", scale=alt.Scale(domain=[0, 1])),
            tooltip=["run_id", "git_sha", "notes", "pitch_accuracy"],
        )
        .properties(height=300)
    )
    st.altair_chart(pitch_chart, use_container_width=True)

    # --- Per-property breakdown (latest run) ---
    if not results_df.empty:
        st.header("Per-Property Error (Latest Run)")
        latest_run_id = summary_df.iloc[-1]["run_id"]
        latest_results = results_df[results_df["run_id"] == latest_run_id]

        if not latest_results.empty:
            bar_chart = (
                alt.Chart(latest_results)
                .mark_bar()
                .encode(
                    x=alt.X("property:N", title="Property", sort="-y"),
                    y=alt.Y("error_pct:Q", title="Error %"),
                    color=alt.condition(
                        alt.datum.error_pct < 10,
                        alt.value("steelblue"),
                        alt.value("coral"),
                    ),
                    tooltip=["property", "address", "error_pct", "measured_sqft", "ref_avg_sqft"],
                )
                .properties(height=300)
            )
            st.altair_chart(bar_chart, use_container_width=True)

    # --- Run history table ---
    st.header("Run History")
    display_cols = [
        "run_id",
        "timestamp",
        "git_sha",
        "mode",
        "avg_error_pct",
        "pitch_accuracy",
        "properties_evaluated",
        "notes",
    ]
    available_cols = [c for c in display_cols if c in summary_df.columns]
    st.dataframe(summary_df[available_cols].sort_values("timestamp", ascending=False), use_container_width=True)

    # --- Comparison view ---
    if len(summary_df) >= 2:
        st.header("Compare Runs")
        run_ids = summary_df["run_id"].tolist()
        col1, col2 = st.columns(2)
        with col1:
            run_a = st.selectbox("Run A", run_ids, index=len(run_ids) - 2)
        with col2:
            run_b = st.selectbox("Run B", run_ids, index=len(run_ids) - 1)

        if run_a and run_b and run_a != run_b:
            sa = summary_df[summary_df["run_id"] == run_a].iloc[0]
            sb = summary_df[summary_df["run_id"] == run_b].iloc[0]
            comparison = pd.DataFrame(
                {
                    "Metric": ["Avg Error %", "Pitch Accuracy", "Properties", "Duration (s)"],
                    f"Run {run_a}": [
                        sa.get("avg_error_pct"),
                        sa.get("pitch_accuracy"),
                        sa.get("properties_evaluated"),
                        sa.get("total_duration_seconds"),
                    ],
                    f"Run {run_b}": [
                        sb.get("avg_error_pct"),
                        sb.get("pitch_accuracy"),
                        sb.get("properties_evaluated"),
                        sb.get("total_duration_seconds"),
                    ],
                }
            )
            st.table(comparison)


if __name__ == "__main__":
    main()
